from flask import Flask, render_template, request, redirect, url_for, flash, session
import boto3
import uuid
from datetime import datetime
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal
import json

app = Flask(__name__)
app.secret_key = "stocker_secret_2024"

# ---------------- AWS CONFIGURATION (IAM ROLE ONLY) ---------------- #

AWS_REGION = "us-east-1"

# boto3 will automatically use the IAM Role attached to EC2
boto3_session = boto3.Session(region_name=AWS_REGION)

# DynamoDB resource
dynamodb = boto3_session.resource('dynamodb')

# SNS client
sns = boto3_session.client('sns')

# DynamoDB Tables
USER_TABLE = "stocker_users"
STOCK_TABLE = "stocker_stocks"
TRANSACTION_TABLE = "stocker_transactions"
PORTFOLIO_TABLE = "stocker_portfolio"

# SNS Topics
USER_ACCOUNT_TOPIC_ARN = "arn:aws:sns:us-east-1:604665149129:StockerUserAccountTopic"
TRANSACTION_TOPIC_ARN = "arn:aws:sns:us-east-1:604665149129:StockerTransactionTopic"


# ---------------- HELPER CLASSES ---------------- #

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


# ---------------- SNS FUNCTION ---------------- #

def send_notification(topic_arn, subject, message, attributes=None):

    if not topic_arn:
        return False

    try:

        kwargs = {
            "TopicArn": topic_arn,
            "Subject": subject,
            "Message": message
        }

        if attributes:
            kwargs["MessageAttributes"] = attributes

        sns.publish(**kwargs)

        return True

    except Exception as e:

        print("SNS Error:", e)
        return False


# ---------------- DATABASE FUNCTIONS ---------------- #

def get_user_by_email(email):

    table = dynamodb.Table(USER_TABLE)

    response = table.get_item(Key={'email': email})

    return response.get("Item")


def create_user(username, email, password, role):

    table = dynamodb.Table(USER_TABLE)

    user = {

        "id": str(uuid.uuid4()),
        "username": username,
        "email": email,
        "password": password,
        "role": role
    }

    table.put_item(Item=user)

    return user


def get_all_stocks():

    table = dynamodb.Table(STOCK_TABLE)

    response = table.scan()

    return response.get("Items", [])


def get_stock_by_id(stock_id):

    table = dynamodb.Table(STOCK_TABLE)

    response = table.get_item(Key={'id': stock_id})

    return response.get("Item")


def get_traders():

    table = dynamodb.Table(USER_TABLE)

    response = table.scan(

        FilterExpression=Attr('role').eq("trader")

    )

    return response.get("Items", [])


def get_user_by_id(user_id):

    table = dynamodb.Table(USER_TABLE)

    response = table.scan(

        FilterExpression=Attr('id').eq(user_id)

    )

    users = response.get("Items", [])

    return users[0] if users else None


def get_transactions():

    table = dynamodb.Table(TRANSACTION_TABLE)

    transactions = table.scan().get("Items", [])

    for t in transactions:

        t["user"] = get_user_by_id(t["user_id"])

        t["stock"] = get_stock_by_id(t["stock_id"])

    return transactions


def get_portfolios():

    table = dynamodb.Table(PORTFOLIO_TABLE)

    portfolios = table.scan().get("Items", [])

    for p in portfolios:

        p["user"] = get_user_by_id(p["user_id"])

        p["stock"] = get_stock_by_id(p["stock_id"])

    return portfolios


def get_user_portfolio(user_id):

    table = dynamodb.Table(PORTFOLIO_TABLE)

    response = table.query(

        KeyConditionExpression=Key("user_id").eq(user_id)

    )

    portfolio = response.get("Items", [])

    for p in portfolio:

        p["stock"] = get_stock_by_id(p["stock_id"])

    return portfolio


def get_portfolio_item(user_id, stock_id):

    table = dynamodb.Table(PORTFOLIO_TABLE)

    response = table.get_item(

        Key={

            "user_id": user_id,

            "stock_id": stock_id

        }

    )

    return response.get("Item")


def create_transaction(user_id, stock_id, action, quantity, price, status='completed'):

    table = dynamodb.Table(TRANSACTION_TABLE)

    transaction = {

        "id": str(uuid.uuid4()),

        "user_id": user_id,

        "stock_id": stock_id,

        "action": action,

        "quantity": quantity,

        "price": Decimal(str(price)),

        "status": status,

        "transaction_date": datetime.now().isoformat()

    }

    table.put_item(Item=transaction)

    return transaction


def update_portfolio(user_id, stock_id, quantity, average_price):

    table = dynamodb.Table(PORTFOLIO_TABLE)

    quantity = Decimal(str(quantity))

    average_price = Decimal(str(average_price))

    existing = get_portfolio_item(user_id, stock_id)

    if existing and quantity > 0:

        table.update_item(

            Key={"user_id": user_id, "stock_id": stock_id},

            UpdateExpression="set quantity=:q, average_price=:p",

            ExpressionAttributeValues={

                ":q": quantity,

                ":p": average_price

            }

        )

    elif existing and quantity <= 0:

        table.delete_item(

            Key={"user_id": user_id, "stock_id": stock_id}

        )

    elif quantity > 0:

        table.put_item(

            Item={

                "user_id": user_id,

                "stock_id": stock_id,

                "quantity": quantity,

                "average_price": average_price

            }

        )


# ------------------- Routes ------------------- #

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        role = request.form.get('role')
        email = request.form.get('email')
        password = request.form.get('password')

        user = get_user_by_email(email)

        if user and user['password'] == password and user['role'] == role:

            session['email'] = user['email']
            session['role'] = user['role']
            session['user_id'] = user['id']

            flash('Login successful!', 'success')

            return redirect(url_for('dashboard_admin' if role == 'admin' else 'dashboard_trader'))

        flash('Invalid credentials', 'danger')

    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():

    if request.method == 'POST':

        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']

        if get_user_by_email(email):

            flash('User already exists', 'warning')
            return redirect(url_for('login'))

        create_user(username, email, password, role)

        flash('Account created', 'success')

        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/dashboard_admin')
def dashboard_admin():

    user = get_user_by_email(session['email'])
    stocks = get_all_stocks()

    return render_template('dashboard_admin.html', user=user, market_data=stocks)


@app.route('/dashboard_trader')
def dashboard_trader():

    user = get_user_by_email(session['email'])
    stocks = get_all_stocks()

    return render_template('dashboard_trader.html', user=user, market_data=stocks)


# ---------------- SERVICE 01 ---------------- #

@app.route('/service01')
def service01():

    traders = get_traders()

    return render_template('service-details-1.html', traders=traders)


# ---------------- SERVICE 02 ---------------- #

@app.route('/service02')
def service02():

    transactions = get_transactions()

    return render_template('service-details-2.html', transactions=transactions)


# ---------------- SERVICE 03 ---------------- #

@app.route('/service03')
def service03():

    portfolios = get_portfolios()

    return render_template('service-details-3.html', portfolios=portfolios)


# ---------------- SERVICE 04 ---------------- #

@app.route('/service04')
def service04():

    user = get_user_by_email(session['email'])
    stocks = get_all_stocks()

    return render_template('service-details-4.html', user=user, stocks=stocks)


# ---------------- SERVICE 05 ---------------- #

@app.route('/service05')
def service05():

    user = get_user_by_email(session['email'])

    portfolio = get_user_portfolio(user['id'])

    transactions = get_transactions()

    return render_template('service-details-5.html', user=user, portfolio=portfolio, transactions=transactions)


@app.route('/logout')
def logout():

    session.clear()

    flash('You have been logged out.', 'info')

    return redirect(url_for('index'))


# ---------------- RUN ---------------- #

if __name__ == '__main__':

    app.run(debug=True, host='0.0.0.0', port=5000)
