from flask import Flask, render_template, request, redirect, session
import uuid
import boto3
import os
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
from utils.data import transport_data, hotel_data 
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "travelgo_secret" 

# AWS Setup - [cite: 2208, 2215]
dynamodb = boto3.resource('dynamodb', region_name='ap-south-1')
sns = boto3.client('sns', region_name='ap-south-1')

# DynamoDB Tables - [cite: 2210, 2211]
users_table = dynamodb.Table('travel-users')
bookings_table = dynamodb.Table('Travel_Bookings')

@app.route('/')
def home():
    return render_template('index.html', logged_in='user' in session)

# Generic search logic to fix empty result issues [cite: 2304]
def get_search_results(category, source, destination):
    data = transport_data.get(category, [])
    return [item for item in data if item['source'].lower() == source.lower() and item['destination'].lower() == destination.lower()]

@app.route('/bus', methods=['GET', 'POST'])
def bus():
    if request.method == 'POST':
        s, d = request.form['source'].strip(), request.form['destination'].strip()
        results = get_search_results('bus', s, d)
        return render_template('bus.html', buses=results, source=s, destination=d)
    return render_template('bus.html', buses=None)

@app.route('/train', methods=['GET', 'POST'])
def train():
    if request.method == 'POST':
        s, d = request.form['source'].strip(), request.form['destination'].strip()
        results = get_search_results('train', s, d)
        return render_template('train.html', trains=results, source=s, destination=d)
    return render_template('train.html', trains=None)

@app.route('/flight', methods=['GET', 'POST'])
def flight():
    if request.method == 'POST':
        s, d = request.form['source'].strip(), request.form['destination'].strip()
        results = get_search_results('flight', s, d)
        return render_template('flight.html', flights=results, source=s, destination=d)
    return render_template('flight.html', flights=None)

@app.route('/hotels', methods=['GET', 'POST'])
def hotels():
    if request.method == 'POST':
        city = request.form.get('city').strip()
        filtered = [h for h in hotel_data if h['location'].lower() == city.lower()]
        return render_template('hotels.html', hotels=filtered, city=city)
    return render_template('hotels.html', hotels=None)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        if 'Item' in users_table.get_item(Key={'email': email}):
            return render_template('register.html', message="User already exists")
        users_table.put_item(Item={'email': email, 'name': request.form['name'], 'password': request.form['password'], 'logins': 0})
        return redirect('/login')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email, password = request.form['email'], request.form['password']
        user = users_table.get_item(Key={'email': email}).get('Item')
        if user and user['password'] == password:
            session['user'] = email
            users_table.update_item(Key={'email': email}, UpdateExpression="ADD logins :inc", ExpressionAttributeValues={':inc': Decimal(1)})
            return redirect('/dashboard')
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user' not in session: return redirect('/login')
    email = session['user']
    user = users_table.get_item(Key={'email': email}).get('Item')
    bookings = bookings_table.scan(FilterExpression=Attr('user_email').eq(email))['Items']
    return render_template('dashboard.html', name=user['name'], bookings=bookings)

@app.route('/book', methods=['POST'])
def book():
    if 'user' not in session: return redirect('/login')
    session['pending_booking'] = {
        "booking_id": str(uuid.uuid4())[:8],
        "type": request.form['type'],
        "source": request.form.get('source', 'N/A'),
        "destination": request.form.get('destination', 'N/A'),
        "date": "N/A", # Fixed date issue by setting default
        "details": request.form['details'],
        "price": Decimal(request.form['price']),
        "user_email": session['user']
    }
    return render_template("payment.html", booking=session['pending_booking'])

@app.route('/payment', methods=['POST'])
def payment():
    if 'user' not in session or 'pending_booking' not in session: 
        return redirect('/login')
    
    # Retrieve booking from session
    booking = session.pop('pending_booking')
    
    # CRITICAL: DynamoDB expects the key 'email' [cite: 289]
    # We ensure it is set from the logged-in user session
    booking['email'] = session['user']
    
    # Capture payment details from the form
    booking['payment_method'] = request.form['method']
    booking['payment_reference'] = request.form['reference']
    
    # Save to Bookings table [cite: 728]
    try:
        bookings_table.put_item(Item=booking)
        
        # Trigger Real-Time Notification via SNS [cite: 731]
        sns.publish(
            TopicArn=os.getenv('SNS_TOPIC_ARN'), 
            Message=f"Booking Confirmed! {booking['details']} for ₹{booking['price']}",
            Subject="TravelGo Booking Confirmation"
        )
    except Exception as e:
        print("Error saving booking:", e)
        
    return redirect('/dashboard')

@app.route('/remove_booking', methods=['POST'])
def remove_booking():
    if 'user' not in session: return redirect('/login')
    bookings_table.delete_item(Key={'email': session['user'], 'booking_id': request.form.get('booking_id')})
    return redirect('/dashboard')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
