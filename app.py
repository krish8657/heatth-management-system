from flask import Flask, render_template, session, redirect, url_for, request, flash, jsonify, send_file
from functools import wraps
import os
import csv
from dotenv import load_dotenv
import base64
import io
from PIL import Image
import datetime
import traceback
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from payment_handler import PaymentHandler
from email_service import EmailService
import stripe
import uuid

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- Configuration ---
# Secret key is required to use sessions (keep it secure!)
app.config['SECRET_KEY'] = os.urandom(24).hex() 

# --- Upload Configuration ---
app.config['UPLOAD_FOLDER'] = 'static/uploads'
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Email Configuration from .env ---
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'your_email@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'your_app_password')

# --- Stripe Configuration from .env ---
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', 'sk_test_YOUR_STRIPE_TEST_KEY_HERE')
STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', 'pk_test_YOUR_STRIPE_TEST_KEY_HERE')

# Check Stripe configuration
if 'YOUR_STRIPE_TEST_KEY_HERE' in stripe.api_key.upper() or 'YOUR_STRIPE_TEST_KEY_HERE' in STRIPE_PUBLISHABLE_KEY.upper():
    print("\n" + "="*80)
    print("⚠️  WARNING: Stripe is NOT configured!")
    print("="*80)
    print("📝 To enable payments, create a .env file with your Stripe keys:")
    print("   STRIPE_SECRET_KEY=sk_test_your_actual_key")
    print("   STRIPE_PUBLISHABLE_KEY=pk_test_your_actual_key")
    print("\n🔗 Get your keys from: https://dashboard.stripe.com/apikeys")
    print("📚 See PAYMENT_SETUP.md for detailed instructions")
    print("="*80 + "\n")
else:
    print("✅ Stripe configured successfully")

# --- Initialize Services ---
email_service = EmailService(
    smtp_server=app.config['MAIL_SERVER'],
    smtp_port=app.config['MAIL_PORT'],
    sender_email=app.config['MAIL_USERNAME'],
    sender_password=app.config['MAIL_PASSWORD']
)

# --- MongoDB Configuration ---
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['health_db']

# Security check for MongoDB
if MONGO_URI == 'mongodb://localhost:27017/':
    print("⚠️  WARNING: Using default MongoDB connection (localhost)")
    print("💡 For production, set MONGO_URI in .env file")
else:
    # Don't print the full URI (may contain credentials)
    if 'mongodb+srv://' in MONGO_URI:
        print("✅ MongoDB Atlas connection configured")
    else:
        print("✅ MongoDB connection configured")

users_collection = db['users']
doctors_collection = db['doctor']
appointments_collection = db['appointments']
lab_tests_collection = db['lab_tests']
specialties_collection = db['specialties']
lab_bookings_collection = db['lab_bookings']
reports_collection = db['reports']
meals_collection = db['meals']
prescriptions_collection = db['prescriptions']
notifications_collection = db['notifications']
payments_collection = db['payments']
invoices_collection = db['invoices']
health_records_collection = db['health_records']

def _generate_meeting_link(appointment_id):
    """Create a stable online room for an appointment."""
    return f"https://meet.jit.si/SmartHealth-{appointment_id}"

def _load_medicine_options():
    """Load doctor prescription choices from the repository medicine dataset."""
    dataset_path = os.path.join(os.path.dirname(__file__), 'medicine_data.csv')
    try:
        with open(dataset_path, newline='', encoding='utf-8') as dataset:
            return [
                {
                    'name': row.get('name', '').strip(),
                    'composition': row.get('short_composition1', '').strip(),
                    'manufacturer': row.get('manufacturer_name', '').strip(),
                }
                for row in csv.DictReader(dataset)
                if row.get('name', '').strip()
            ]
    except OSError as exc:
        app.logger.error("Unable to load medicine dataset: %s", exc)
        return []


MEDICINE_OPTIONS = _load_medicine_options()
# Lab price helper
def _get_lab_test_price(test):
    if not test:
        return 0
    for key in ('price', 'cost', 'amount'):
        val = test.get(key)
        if val is not None and val != '':
            try:
                return float(val)
            except Exception:
                pass
    return 0

# Check daily test limit (5 per day per hospital)
def _check_daily_test_limit(hospital_id, scheduled_date):
    """Check if hospital already has 5 tests scheduled for the given date."""
    if not hospital_id or not scheduled_date:
        return False
    count = lab_bookings_collection.count_documents({
        'hospital_id': hospital_id,
        'scheduled_date': scheduled_date,
        'status': {'$in': ['Scheduled', 'Test Done']}
    })
    return count >= 5

def _get_booked_slots(hospital_id, scheduled_date):
    """Get all time slots already booked for the given hospital and date."""
    if not hospital_id or not scheduled_date:
        return []
    bookings = lab_bookings_collection.find({
        'hospital_id': hospital_id,
        'scheduled_date': scheduled_date,
        'scheduled_time': {'$exists': True, '$ne': None},
        'status': {'$in': ['Scheduled', 'Test Done']}
    })
    booked_times = [booking.get('scheduled_time') for booking in bookings if booking.get('scheduled_time')]
    return booked_times

# Refund helper
def _issue_refund(payment_intent_id):
    if not payment_intent_id:
        return False, 'Missing payment intent id'
    if not stripe.api_key or 'YOUR_STRIPE_TEST_KEY_HERE' in stripe.api_key:
        return False, 'Stripe is not configured'
    try:
        refund = stripe.Refund.create(payment_intent=payment_intent_id)
        return True, refund
    except stripe.error.StripeError as e:
        return False, str(e)
# Prefer a dedicated Atlas database named 'hospitals' if present (some clusters use that DB)
try:
    db_names = client.list_database_names()
except Exception:
    db_names = []

if 'hospitals' in db_names:
    try:
        hospitals_db = client['hospitals']
        if 'hospitals' in hospitals_db.list_collection_names():
            hospitals_collection = hospitals_db['hospitals']
        else:
            hospitals_collection = db['hospitals']
    except Exception:
        hospitals_collection = db['hospitals']
else:
    hospitals_collection = db['hospitals']

# --- Login Required Decorator ---
# Use this to protect routes that guests should not access
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # If not logged in, send them to the auth page
            return redirect(url_for('auth_page'))
        return f(*args, **kwargs)
    return decorated_function

def doctor_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'doctor_id' not in session:
            return redirect(url_for('auth_page'))
        return f(*args, **kwargs)
    return decorated_function


def hospital_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'hospital_id' not in session:
            return redirect(url_for('auth_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- Helper Function: Send Email ---
def send_email(to_email, subject, body):
    return email_service.send_email(to_email, subject, body)

# ==========================================
# 1. PUBLIC ROUTES (Accessible to everyone)
# ==========================================

@app.route('/')
def dashboard():
    """Main homepage - visible to everyone."""
    logged_in = 'user_id' in session
    user = None
    if logged_in:
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
    return render_template('dashboard.html', logged_in=logged_in, user=user)

@app.route('/auth')
def auth_page():
    """Single page containing both Login and Register forms."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('auth.html')

@app.route('/register-patient')
def register_patient():
    """Dedicated patient registration page."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('register.html')

@app.route('/doctors')
def view_doctors():
    """Feature: View All Doctors with Filters."""
    # Get filter parameters
    specialty_filter = request.args.get('specialty')
    gender_filter = request.args.get('gender')
    experience_filter = request.args.get('experience')
    sort_price = request.args.get('sort_price')
    search_query = request.args.get('search')

    query = {}
    if specialty_filter:
        query['specialty'] = specialty_filter
    if search_query:
        query['name'] = {'$regex': search_query, '$options': 'i'}
        
    if gender_filter:
        query['gender'] = gender_filter
    
    if experience_filter:
        # Filter doctors with experience >= selected value
        query['experience_years'] = {'$gte': int(experience_filter)}
        
    # Only show doctors who have completed their profile (have fees set)
    query['consultation_fees'] = {'$exists': True, '$ne': None}

    # Fetch doctors
    doctors_cursor = doctors_collection.find(query)
    doctors_list = list(doctors_cursor)

    # Sorting by Price
    if sort_price == 'asc':
        doctors_list.sort(key=lambda x: x.get('consultation_fees', 0))
    elif sort_price == 'desc':
        doctors_list.sort(key=lambda x: x.get('consultation_fees', 0), reverse=True)

    # Get specialties for dropdown
    specialties = list(specialties_collection.find({}, {'name': 1, 'icon': 1, '_id': 0}))

    return render_template('doctors_list.html', 
                           doctors=doctors_list, 
                           specialties=specialties,
                           selected_specialty=specialty_filter,
                           selected_gender=gender_filter,
                           selected_experience=experience_filter,
                           selected_sort=sort_price,
                           logged_in='user_id' in session)

@app.route('/doctors/<path:specialty>')
def view_doctors_by_specialty(specialty):
    """Redirect old route to new filter route."""
    return redirect(url_for('view_doctors', specialty=specialty))

@app.route('/lab_tests')
def view_lab_tests():
    """Feature: Browse Lab Tests (Public) with hospital filtering."""
    category_filter = request.args.get('category')
    hospital_filter = request.args.get('hospital')
    query = {}
    
    if category_filter:
        query['category'] = category_filter
    
    if hospital_filter:
        query['available_at'] = hospital_filter
        
    tests = list(lab_tests_collection.find(query))
    categories = lab_tests_collection.distinct('category')
    
    # Get all hospitals for the search dropdown
    hospitals = list(hospitals_collection.find({}, {'name': 1, 'address': 1, 'rating': 1}))
    
    # Get today's date and max date (1 week from today) in YYYY-MM-DD format for date picker
    today = datetime.datetime.now()
    today_date = today.strftime('%Y-%m-%d')
    max_date = (today + datetime.timedelta(days=7)).strftime('%Y-%m-%d')
    
    return render_template('lab_tests.html', 
                         tests=tests, 
                         categories=categories, 
                         hospitals=hospitals,
                         selected_category=category_filter,
                         selected_hospital=hospital_filter,
                         logged_in='user_id' in session,
                         today_date=today_date,
                         max_date=max_date)

@app.route('/health_tips')
def health_tips():
    """Render the public daily health tips page."""
    return render_template('health_tips.html')

@app.route('/health_articles')
def health_articles():
    """Render the public health articles page."""
    return render_template('health_articles.html')

# ==========================================
# DOCTOR STATUS API (For Dynamic Updates)
# ==========================================

@app.route('/api/doctor-statuses')
def get_doctor_statuses():
    """API endpoint to fetch all doctor availability statuses with duration info."""
    doctors = list(doctors_collection.find({}, {
        '_id': 1, 
        'name': 1, 
        'availability_status': 1,
        'leave_start_date': 1,
        'leave_end_date': 1,
        'busy_start_time': 1,
        'busy_end_time': 1
    }))
    # Convert ObjectId to string for JSON serialization
    for doctor in doctors:
        doctor['_id'] = str(doctor['_id'])
    return jsonify(doctors)

@app.route('/api/doctor/<doctor_id>/status')
def get_doctor_status(doctor_id):
    """API endpoint to fetch a single doctor's status."""
    try:
        doctor = doctors_collection.find_one({'_id': ObjectId(doctor_id)})
        if doctor:
            return jsonify({
                '_id': str(doctor['_id']),
                'name': doctor.get('name'),
                'availability_status': doctor.get('availability_status', 'Available')
            })
        return jsonify({'error': 'Doctor not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# ==========================================
# PAYMENT & CHECKOUT ROUTES
# ==========================================

@app.route('/checkout/appointment/<appointment_id>')
@login_required
def checkout_appointment(appointment_id):
    """Display payment page for appointment."""
    appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id)})
    if not appointment:
        flash("Appointment not found.", "error")
        return redirect(url_for('inbox'))

    if appointment.get('status') in ['Cancelled', 'Declined', 'Completed']:
        flash("This appointment is not eligible for payment.", "error")
        return redirect(url_for('inbox'))
    
    user_id = session['user_id']
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    doctor = doctors_collection.find_one({'name': appointment.get('doctor_name')})
    
    # Get consultation fees
    fees = doctor.get('consultation_fees', 0) if doctor else 0
    subtotal = fees
    tax = subtotal * 0.10
    total = subtotal + tax
    
    items = [{
        'description': f'Consultation with Dr. {appointment.get("doctor_name")}',
        'quantity': 1,
        'price': fees
    }]
    
    return render_template('payment.html',
                         items=items,
                         subtotal=subtotal,
                         tax=tax,
                         total=total,
                         appointment_id=appointment_id,
                         doctor_name=appointment.get('doctor_name'),
                         appointment_date=appointment.get('date'),
                         payment_url=url_for('process_payment_appointment', appointment_id=appointment_id),
                         back_url=url_for('inbox'),
                         stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                         logged_in=True)

@app.route('/checkout/lab_test', methods=['GET', 'POST'])
@login_required
def checkout_lab_test():
    """Display payment page for lab test with hospital selection."""
    booking_id = request.args.get('booking_id')
    test_name = request.args.get('test_name')

    if not booking_id:
        flash("Payment is available only after hospital approval.", "error")
        return redirect(url_for('inbox'))

    booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
    if not booking:
        flash("Lab booking not found.", "error")
        return redirect(url_for('inbox'))

    if booking.get('status') not in ['Approved', 'Scheduled', 'Awaiting Payment']:
        flash("Your booking is not approved yet. Payment will be enabled after approval.", "error")
        return redirect(url_for('inbox'))

    if booking.get('payment_status') == 'completed':
        flash("Payment already completed for this booking.", "info")
        return redirect(url_for('inbox'))

    test_name = booking.get('test_name')
    selected_hospital_id = booking.get('hospital_id', '')
    selected_hospital_name = booking.get('hospital_name', '')
    test = lab_tests_collection.find_one({'name': test_name})

    if not test:
        flash("Lab test not found.", "error")
        return redirect(url_for('inbox'))
    
    cost = _get_lab_test_price(test)
    subtotal = cost
    tax = subtotal * 0.10
    total = subtotal + tax
    
    items = [{
        'description': f'{test.get("name")} - Lab Test',
        'quantity': 1,
        'price': cost
    }]
    
    # Add hospital info to items if selected
    if selected_hospital_name:
        items[0]['description'] = f'{test.get("name")} at {selected_hospital_name}'
    
    return render_template('payment.html',
                         items=items,
                         subtotal=subtotal,
                         tax=tax,
                         total=total,
                         test_name=test_name,
                         booking_id=str(booking_id),
                         hospital_name=selected_hospital_name,
                         payment_url=url_for('process_payment_lab_test'),
                         back_url=url_for('inbox'),
                         stripe_publishable_key=STRIPE_PUBLISHABLE_KEY,
                         logged_in=True)

@app.route('/process_payment/appointment/<appointment_id>', methods=['POST'])
@login_required
def process_payment_appointment(appointment_id):
    """Process payment for appointment using Stripe."""
    try:
        # Validate Stripe configuration
        if not stripe.api_key or 'YOUR_STRIPE_TEST_KEY_HERE' in stripe.api_key.upper():
            print("❌ Stripe Error: API key not configured")
            return jsonify({'success': False, 'message': 'Stripe is not configured. Please add your Stripe keys to .env file.'}), 400
        
        data = request.get_json()
        appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id)})
        if not appointment:
            print(f"❌ Appointment not found: {appointment_id}")
            return jsonify({'success': False, 'message': 'Appointment not found'}), 404
            
        if appointment.get('status') in ['Cancelled', 'Declined', 'Completed']:
            print(f"❌ Appointment status invalid: {appointment.get('status')}")
            return jsonify({'success': False, 'message': 'Appointment is not eligible for payment'}), 400
        
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        doctor = doctors_collection.find_one({'name': appointment.get('doctor_name')})
        
        if not doctor:
            print(f"❌ Doctor not found: {appointment.get('doctor_name')}")
            return jsonify({'success': False, 'message': 'Doctor information not found'}), 404
        
        fees = doctor.get('consultation_fees', 0) if doctor else 0
        print(f"💰 Consultation fee: ₹{fees}")
        
        if fees <= 0:
            print(f"❌ Invalid fee amount: {fees}")
            return jsonify({'success': False, 'message': 'Invalid consultation fee. Please contact support.'}), 400
            
        amount_cents = int(fees * 100)
        print(f"💳 Creating payment intent for ${amount_cents/100} ({amount_cents} cents)")
        
        # Create payment intent
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency='usd',
                metadata={
                    'appointment_id': appointment_id,
                    'user_id': session['user_id'],
                    'type': 'appointment'
                },
                description=f'Appointment with Dr. {appointment.get("doctor_name")}'
            )
            print(f"✅ Payment intent created: {intent['id']}")
        except stripe.error.AuthenticationError as e:
            print(f"❌ Stripe Authentication Error: {str(e)}")
            return jsonify({'success': False, 'message': 'Stripe authentication failed. Check your API keys in .env file.'}), 400
        except stripe.error.APIConnectionError as e:
            print(f"❌ Stripe Connection Error: {str(e)}")
            return jsonify({'success': False, 'message': 'Cannot connect to Stripe. Check your internet connection.'}), 400
        
        # Store payment record
        payment_record = {
            'appointment_id': appointment_id,
            'user_id': session['user_id'],
            'doctor_name': appointment.get('doctor_name'),
            'amount': fees,
            'payment_intent_id': intent['id'],
            'status': 'pending',
            'created_at': datetime.datetime.now()
        }
        payments_collection.insert_one(payment_record)
        
        # Update appointment status
        appointments_collection.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': {'payment_status': 'pending', 'payment_intent_id': intent['id']}}
        )
        
        print(f"✅ Payment intent successful for appointment {appointment_id}")
        return jsonify({
            'success': True,
            'client_secret': intent['client_secret']
        })
    except stripe.error.CardError as e:
        error_msg = f"Card Error: {e.user_message}" if hasattr(e, 'user_message') else f"Card declined: {str(e)}"
        print(f"❌ Card Error: {error_msg}")
        return jsonify({'success': False, 'message': error_msg}), 400
    except stripe.error.InvalidRequestError as e:
        print(f"❌ Invalid Request Error: {str(e)}")
        return jsonify({'success': False, 'message': f"Invalid request: {str(e)}"}), 400
    except stripe.error.StripeError as e:
        print(f"❌ Stripe Error: {str(e)}")
        return jsonify({'success': False, 'message': f"Payment error: {str(e)}"}), 400
    except Exception as e:
        print(f"❌ Unexpected Payment Error:\n{traceback.format_exc()}")
        return jsonify({'success': False, 'message': f"An error occurred: {str(e)}"}), 500

@app.route('/payment_success/appointment/<appointment_id>')
@login_required
def payment_success_appointment(appointment_id):
    """Handle successful appointment payment."""
    import sys
    import traceback
    print(f"\n\n🔴 FUNCTION STARTED: payment_success_appointment()")
    sys.stdout.flush()
    print(f"Appointment ID: {appointment_id}")
    sys.stdout.flush()
    
    try:
        try:
            print(f"🔍 STEP 0: Fetching appointment from database...")
            sys.stdout.flush()
            appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id)})
            if not appointment:
                print(f"❌ ERROR: Appointment not found with ID: {appointment_id}")
                sys.stdout.flush()
                raise Exception(f"Appointment not found: {appointment_id}")
            print(f"✅ Appointment found")
            sys.stdout.flush()
            
            print(f"🔍 STEP 0B: Fetching user from database...")
            sys.stdout.flush()
            user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
            if not user:
                print(f"❌ ERROR: User not found with ID: {session['user_id']}")
                sys.stdout.flush()
                raise Exception(f"User not found: {session['user_id']}")
            print(f"✅ User found: {user.get('username')}")
            sys.stdout.flush()
            
            print(f"🔍 STEP 0C: Fetching doctor from database...")
            sys.stdout.flush()
            doctor = doctors_collection.find_one({'name': appointment.get('doctor_name')})
            if not doctor:
                print(f"⚠️  WARNING: Doctor not found with name: {appointment.get('doctor_name')}")
                sys.stdout.flush()
            else:
                print(f"✅ Doctor found: {doctor.get('name')}")
                sys.stdout.flush()
        except Exception as e:
            print(f"❌ ERROR in data fetching: {str(e)}")
            sys.stdout.flush()
            print(f"Exception type: {type(e).__name__}")
            sys.stdout.flush()
            traceback.print_exc()
            raise
        
        # Update appointment status
        appointments_collection.update_one(
            {'_id': ObjectId(appointment_id)},
            {'$set': {
                'payment_status': 'completed',
                'status': 'Confirmed',
                'meeting_link': appointment.get('meeting_link') or _generate_meeting_link(appointment_id)
            }}
        )
        appointment['meeting_link'] = appointment.get('meeting_link') or _generate_meeting_link(appointment_id)
        
        # Update payment record
        payments_collection.update_one(
            {'appointment_id': appointment_id},
            {'$set': {'status': 'completed', 'completed_at': datetime.datetime.now()}}
        )
        
        # Generate invoice with complete appointment details
        fees = doctor.get('consultation_fees', 0) if doctor else 0
        tax = fees * 0.10
        total = fees + tax
        
        invoice_data = {
            'user_name': user.get('username', 'Patient'),
            'user_email': user.get('email', ''),
            'invoice_id': f"INV-{uuid.uuid4().hex[:8].upper()}",
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'items': [{
                'description': f'Consultation with Dr. {appointment.get("doctor_name")}',
                'quantity': 1,
                'price': fees
            }],
            'subtotal': fees,
            'tax': tax,
            'total': total,
            # Enhanced appointment details for invoice
            'doctor_name': appointment.get('doctor_name'),
            'appointment_date': appointment.get('date', 'TBD'),
            'appointment_time': appointment.get('time', 'To be scheduled'),
            'symptoms': appointment.get('symptoms', 'General Consultation'),
            'clinic_address': doctor.get('clinic_address', 'Online Consultation') if doctor else 'Online Consultation',
            'consultation_type': doctor.get('consultation_type', 'Online') if doctor else 'Online',
            'payment_method': 'Stripe Card Payment',
            'payment_status': 'PAID'
        }
        
        # Generate invoice PDF with error handling
        print("\n📄 GENERATING INVOICE PDF...")
        sys.stdout.flush()
        try:
            invoice_pdf = PaymentHandler.generate_invoice(invoice_data)
            invoice_filename = f"invoice_{uuid.uuid4().hex[:8]}.pdf"
            invoice_path = os.path.join(app.config['UPLOAD_FOLDER'], invoice_filename)
            
            print(f"✅ Invoice PDF generated in memory")
            sys.stdout.flush()
            print(f"📁 Saving to: {invoice_path}")
            sys.stdout.flush()
            
            with open(invoice_path, 'wb') as f:
                f.write(invoice_pdf.getvalue())
            
            print(f"✅ Invoice saved successfully: {invoice_filename}")
            sys.stdout.flush()
            print(f"📊 File size: {os.path.getsize(invoice_path)} bytes")
            sys.stdout.flush()
        except Exception as e:
            print(f"❌ ERROR generating invoice PDF: {str(e)}")
            sys.stdout.flush()
            traceback.print_exc()
            # Create a simple text file as fallback
            invoice_filename = f"invoice_{uuid.uuid4().hex[:8]}.txt"
            invoice_path = os.path.join(app.config['UPLOAD_FOLDER'], invoice_filename)
            with open(invoice_path, 'w') as f:
                f.write(f"Invoice {invoice_data['invoice_id']}\n")
                f.write(f"Patient: {invoice_data['user_name']}\n")
                f.write(f"Amount: ₹{total}\n")
            print(f"⚠️  Created fallback text invoice: {invoice_filename}")
            sys.stdout.flush()
        
        # Store invoice in database
        invoice_record = {
            'invoice_id': invoice_data['invoice_id'],
            'user_id': session['user_id'],
            'appointment_id': appointment_id,
            'amount': total,
            'filename': invoice_filename,
            'created_at': datetime.datetime.now()
        }
        res = invoices_collection.insert_one(invoice_record)
        invoice_db_id = str(res.inserted_id)
        # Build full invoice URL for email
        try:
            invoice_url = request.url_root.rstrip('/') + url_for('download_invoice', invoice_id=invoice_db_id)
        except Exception:
            invoice_url = None
        
        # Send confirmation email with invoice
        payment_info = {
            'transaction_id': appointment.get('payment_intent_id', 'N/A'),
            'amount': total,
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'method': 'Stripe Card',
            'description': f'Appointment with Dr. {appointment.get("doctor_name")}'
        }
        
        # Send appointment confirmation email
        appointment_data = {
            'doctor_name': appointment.get('doctor_name'),
            'date': appointment.get('date'),
            'time': appointment.get('time', 'To be scheduled'),
            'fees': fees,
            'symptoms': appointment.get('symptoms', ''),
            'clinic_address': doctor.get('clinic_address', 'Location TBD') if doctor else 'Location TBD',
            'consultation_type': 'Online',
            'meeting_link': appointment.get('meeting_link')
        }
        
        # Verify user email exists
        user_email = user.get('email')
        import sys
        print(f"\n{'='*60}")
        sys.stdout.flush()
        print(f"📧 PAYMENT SUCCESS - EMAIL SENDING PROCESS")
        sys.stdout.flush()
        print(f"{'='*60}")
        sys.stdout.flush()
        print(f"User: {user.get('username')} ({user_email})")
        sys.stdout.flush()
        print(f"Doctor: {appointment.get('doctor_name')}")
        sys.stdout.flush()
        print(f"Amount: ₹{total}")
        sys.stdout.flush()
        print(f"Invoice: {invoice_data['invoice_id']}")
        sys.stdout.flush()
        print(f"{'='*60}\n")
        sys.stdout.flush()
        
        if not user_email:
            print("❌ ERROR: User email not found in database!")
            sys.stdout.flush()
        else:
            try:
                print(f"\n{'='*60}")
                print(f"📧 SENDING COMBINED APPOINTMENT + PAYMENT EMAIL")
                print(f"{'='*60}")
                print(f"To: {user_email}")
                print(f"Doctor: {appointment_data.get('doctor_name')}")
                print(f"Date: {appointment_data.get('date')} at {appointment_data.get('time')}")
                print(f"Amount: ₹{total}")
                print(f"Invoice ID: {invoice_data['invoice_id']}")
                print(f"{'='*60}\n")
                sys.stdout.flush()
                
                # Add transaction info to payment_info for email
                payment_info['invoice_id'] = invoice_data['invoice_id']
                payment_info['tax'] = tax
                
                combined_email_sent = email_service.send_combined_appointment_payment_email(
                    user_email,
                    user.get('username'),
                    appointment_data,
                    payment_info,
                    invoice_path,
                    invoice_url=invoice_url
                )
                if combined_email_sent:
                    print("✅ Combined appointment + payment email sent successfully\n")
                    sys.stdout.flush()
                else:
                    print("⚠️  Combined email failed to send\n")
                    sys.stdout.flush()
                    
                print(f"{'='*60}")
                sys.stdout.flush()
                print("✅ EMAIL SENT SUCCESSFULLY")
                sys.stdout.flush()
                print(f"{'='*60}\n")
                sys.stdout.flush()
                    
            except Exception as e:
                print(f"\n❌ ERROR SENDING EMAIL: {str(e)}")
                sys.stdout.flush()
                print(f"Exception Type: {type(e).__name__}")
                sys.stdout.flush()
                print(f"User Email: {user_email}")
                sys.stdout.flush()
                print(f"Invoice Path: {invoice_path}")
                print(f"Invoice Path Exists: {os.path.exists(invoice_path)}")
                traceback.print_exc()
                print(f"{'='*60}\n")
        
        # Create notification (expires at appointment time if available)
        notif = {
            'user_id': session['user_id'],
            'title': 'Payment Successful',
            'message': f'Your appointment payment of ₹{total:.2f} has been confirmed.',
            'time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            'created_at': datetime.datetime.now()
        }
        try:
            appt_date = appointment.get('date')
            appt_time = appointment.get('time')
            if appt_date and appt_time:
                appt_dt = datetime.datetime.strptime(f"{appt_date} {appt_time}", "%Y-%m-%d %H:%M")
                notif['expires_at'] = appt_dt
        except Exception:
            pass
        # attach invoice reference to notification if available
        try:
            if invoice_db_id:
                notif['invoice_id'] = invoice_db_id
                notif['invoice_url'] = invoice_url
        except Exception:
            pass
        notifications_collection.insert_one(notif)
        
        # If called via AJAX, return JSON; otherwise redirect
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': True, 'message': 'Payment processed successfully'}), 200
        
        flash("Payment successful! Your appointment has been confirmed.", "success")
        return redirect(url_for('inbox'))
        
    except Exception as e:
        print(f"\n❌ OUTER EXCEPTION in payment_success_appointment():")
        sys.stdout.flush()
        print(f"Error: {str(e)}")
        sys.stdout.flush()
        print(f"Exception Type: {type(e).__name__}")
        sys.stdout.flush()
        traceback.print_exc()
        sys.stdout.flush()
        
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error processing payment: {str(e)}", "error")
        return redirect(url_for('checkout_appointment', appointment_id=appointment_id))

@app.route('/process_payment/lab_test', methods=['POST'])
@login_required
def process_payment_lab_test():
    """Process payment for lab test using Stripe."""
    try:
        # Validate Stripe configuration
        if not stripe.api_key or 'YOUR_STRIPE_TEST_KEY_HERE' in stripe.api_key:
            return jsonify({'success': False, 'message': 'Stripe is not configured. Please contact support.'}), 400
        
        data = request.get_json()
        booking_id = data.get('booking_id')
        if not booking_id:
            return jsonify({'success': False, 'message': 'Booking ID is required for payment'}), 400

        booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
        if not booking:
            return jsonify({'success': False, 'message': 'Lab booking not found'}), 404

        if booking.get('status') not in ['Approved', 'Scheduled', 'Awaiting Payment']:
            return jsonify({'success': False, 'message': 'Payment is available only after hospital approval'}), 400

        if booking.get('payment_status') == 'completed':
            return jsonify({'success': False, 'message': 'Payment already completed for this booking'}), 400

        test_name = booking.get('test_name')
        test = lab_tests_collection.find_one({'name': test_name})

        if not test:
            return jsonify({'success': False, 'message': 'Lab test not found'}), 404

        # Get hospital_id from the booking
        hospital_id = booking.get('hospital_id')

        cost = _get_lab_test_price(test)
        if cost <= 0:
            return jsonify({'success': False, 'message': 'Invalid test price'}), 400
            
        amount_cents = int(cost * 100)
        
        # Create payment intent
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            metadata={
                'test_name': test_name,
                'user_id': session['user_id'],
                'type': 'lab_test',
                'hospital_id': str(hospital_id) if hospital_id else None,
                'booking_id': str(booking_id)
            },
            description=f'Lab Test: {test_name}'
        )
        
        # Store payment record
        payment_record = {
            'test_name': test_name,
            'user_id': session['user_id'],
            'amount': cost,
            'payment_intent_id': intent['id'],
            'status': 'pending',
            'created_at': datetime.datetime.now(),
            'hospital_id': hospital_id,
            'booking_id': booking_id
        }
        payments_collection.insert_one(payment_record)

        # Update booking with payment intent
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {'payment_status': 'pending', 'payment_intent_id': intent['id']}}
        )
        
        return jsonify({
            'success': True,
            'client_secret': intent['client_secret']
        })
    except stripe.error.CardError as e:
        error_msg = f"Card Error: {e.user_message}" if hasattr(e, 'user_message') else f"Card declined: {str(e)}"
        return jsonify({'success': False, 'message': error_msg}), 400
    except stripe.error.InvalidRequestError as e:
        return jsonify({'success': False, 'message': f"Invalid request: {str(e)}"}), 400
    except stripe.error.StripeError as e:
        return jsonify({'success': False, 'message': f"Payment error: {str(e)}"}), 400
    except Exception as e:
        print(f"Lab payment error: {traceback.format_exc()}")
        return jsonify({'success': False, 'message': f"An error occurred: {str(e)}"}), 500

@app.route('/payment_success/lab_test')
@login_required
def payment_success_lab_test():
    """Handle successful lab test payment."""
    try:
        booking_id = request.args.get('booking_id')
        if not booking_id:
            return jsonify({'success': False, 'message': 'Booking ID is required'}), 400

        booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
        if not booking:
            if request.headers.get('Accept') == 'application/json' or request.is_json:
                return jsonify({'success': False, 'message': 'Lab booking not found'}), 404
            flash("Lab booking not found.", "error")
            return redirect(url_for('inbox'))

        test_name = booking.get('test_name')
        test = lab_tests_collection.find_one({'name': test_name})
        user = users_collection.find_one({'_id': ObjectId(session['user_id'])})
        
        if not test:
            if request.headers.get('Accept') == 'application/json' or request.is_json:
                return jsonify({'success': False, 'message': 'Lab test not found'}), 404
            flash("Lab test not found.", "error")
            return redirect(url_for('view_lab_tests'))
        
        cost = _get_lab_test_price(test)
        tax = cost * 0.10
        total = cost + tax

        hospital_id = booking.get('hospital_id', '')
        hospital_name = booking.get('hospital_name', '')

        # Update booking as paid/confirmed (set to Scheduled after payment)
        new_status = 'Scheduled' if booking.get('scheduled_date') and booking.get('scheduled_time') else 'Confirmed'
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {
                'payment_status': 'completed',
                'status': 'Scheduled',  # Always set to Scheduled after payment (time was already set during approval)
                'paid_at': datetime.datetime.now(),
                'schedule_pending_payment': False
            }}
        )
        
        # Update payment record
        payments_collection.update_one(
            {'booking_id': booking_id, 'user_id': session['user_id']},
            {'$set': {'status': 'completed', 'completed_at': datetime.datetime.now()}}
        )
        
        # Generate invoice
        invoice_data = {
            'user_name': user.get('username', 'Patient'),
            'user_email': user.get('email', ''),
            'invoice_id': f"INV-{uuid.uuid4().hex[:8].upper()}",
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'items': [{
                'description': f'Lab Test: {test_name}',
                'quantity': 1,
                'price': cost
            }],
            'subtotal': cost,
            'tax': tax,
            'total': total
        }
        
        # Generate invoice PDF
        invoice_pdf = PaymentHandler.generate_invoice(invoice_data)
        invoice_filename = f"invoice_{uuid.uuid4().hex[:8]}.pdf"
        invoice_path = os.path.join(app.config['UPLOAD_FOLDER'], invoice_filename)
        
        with open(invoice_path, 'wb') as f:
            f.write(invoice_pdf.getvalue())
        
        # Store invoice
        invoice_record = {
            'invoice_id': invoice_data['invoice_id'],
            'user_id': session['user_id'],
            'test_name': test_name,
            'amount': total,
            'filename': invoice_filename,
            'created_at': datetime.datetime.now(),
            'booking_id': booking_id,
            'hospital_name': hospital_name
        }
        res = invoices_collection.insert_one(invoice_record)
        invoice_db_id = str(res.inserted_id)
        try:
            invoice_url = request.url_root.rstrip('/') + url_for('download_invoice', invoice_id=invoice_db_id)
        except Exception:
            invoice_url = None
        
        # Send confirmation emails
        lab_data = {
            'test_name': test_name,
            'date': datetime.datetime.now().strftime('%Y-%m-%d'),
            'cost': cost,
            'scheduled_date': booking.get('scheduled_date'),
            'scheduled_time': booking.get('scheduled_time')
        }
        
        payment_info = {
            'transaction_id': 'STRIPE_' + str(uuid.uuid4().hex[:8]).upper(),
            'amount': total,
            'invoice_id': invoice_data['invoice_id'],
            'date': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
            'method': 'Stripe Card',
            'tax': tax,
            'description': f'Lab Test: {test_name}'
        }
        
        # Enhance lab_data with hospital info
        lab_data['hospital_name'] = hospital_name or 'Standard Lab'
        lab_data['booking_date'] = booking.get('booking_date') or datetime.datetime.now().strftime('%Y-%m-%d')
        lab_data['address'] = 'Lab location will be confirmed by hospital'
        
        try:
            print(f"\n{'='*60}")
            print(f"📧 SENDING COMBINED LAB TEST + PAYMENT EMAIL")
            print(f"{'='*60}")
            print(f"To: {user.get('email')}")
            print(f"Test: {test_name}")
            print(f"Amount: ₹{total}")
            print(f"Invoice ID: {invoice_data['invoice_id']}")
            print(f"Scheduled Date: {lab_data.get('scheduled_date')}")
            print(f"Scheduled Time: {lab_data.get('scheduled_time')}")
            print(f"Invoice Path: {invoice_path}")
            print(f"Invoice URL: {invoice_url}")
            print(f"{'='*60}\n")
            
            combined_email_sent = email_service.send_combined_lab_payment_email(
                user.get('email'),
                user.get('username'),
                lab_data,
                payment_info,
                invoice_file_path=invoice_path,
                invoice_url=invoice_url
            )
            if combined_email_sent:
                print("✅ Combined lab test + payment email sent successfully")
            else:
                print("⚠️  Combined email failed to send")
        except Exception as e:
            print(f"❌ Error sending combined lab test email: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Create notification (expires end of day)
        schedule_msg = ''
        if booking.get('scheduled_date') and booking.get('scheduled_time'):
            schedule_msg = f" Scheduled on {booking.get('scheduled_date')} at {booking.get('scheduled_time')}."
        notif = {
            'user_id': session['user_id'],
            'title': 'Lab Test Booked',
            'message': f'Your lab test "{test_name}" has been booked and confirmed. Payment: ₹{total:.2f}.{schedule_msg}',
            'time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            'created_at': datetime.datetime.now()
        }
        try:
            notif['expires_at'] = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
        except Exception:
            pass
        # attach invoice reference if available
        try:
            notif['invoice_id'] = invoice_db_id
            notif['invoice_url'] = invoice_url
        except Exception:
            pass
        notifications_collection.insert_one(notif)
        
        # If called via AJAX, return JSON; otherwise redirect to scheduled page
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': True, 'message': 'Lab test payment processed successfully'}), 200
        
        flash("Payment completed! Check your email for confirmation.", "success")
        return redirect(url_for('lab_test_scheduled', booking_id=booking_id))
        
    except Exception as e:
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error processing lab test payment: {str(e)}", "error")
        return redirect(url_for('view_lab_tests'))

@app.route('/lab/awaiting-payment/<booking_id>')
@login_required
def lab_awaiting_payment(booking_id):
    """Show awaiting payment page for lab booking."""
    try:
        booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
        if not booking:
            flash("Lab booking not found.", "error")
            return redirect(url_for('inbox'))
        
        try:
            booking['_id_str'] = str(booking.get('_id'))
        except Exception:
            booking['_id_str'] = None
        
        # Get test details for price
        test = lab_tests_collection.find_one({'name': booking.get('test_name')})
        cost = _get_lab_test_price(test) if test else 0
        tax = cost * 0.10
        total = cost + tax
        
        return render_template('lab_awaiting_payment.html',
                             lab=booking,
                             cost=cost,
                             tax=f"{tax:.2f}",
                             total=f"{total:.2f}")
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('inbox'))

@app.route('/lab/scheduled/<booking_id>')
@login_required
def lab_test_scheduled(booking_id):
    """Show scheduled page after payment."""
    try:
        booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
        if not booking:
            flash("Lab booking not found.", "error")
            return redirect(url_for('inbox'))
        
        # Get test details for price
        test = lab_tests_collection.find_one({'name': booking.get('test_name')})
        cost = _get_lab_test_price(test) if test else 0
        tax = cost * 0.10
        total = cost + tax
        
        return render_template('lab_scheduled.html',
                             lab=booking,
                             cost=cost,
                             tax=f"{tax:.2f}",
                             total=f"{total:.2f}")
    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('inbox'))

@app.route('/lab/mark-done/<booking_id>', methods=['POST'])
@login_required
def lab_mark_done(booking_id):
    """Mark lab test as done and ready for reports."""
    try:
        booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
        if not booking:
            return jsonify({'success': False, 'message': 'Lab booking not found'}), 404
        
        # Update status to "Report Pending"
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {'status': 'Report Pending', 'test_completed_at': datetime.datetime.now()}}
        )
        
        return jsonify({'success': True, 'message': 'Test marked as done'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/lab/upload-reports/<booking_id>', methods=['GET', 'POST'])
@login_required
def lab_upload_reports(booking_id):
    """Upload lab test reports."""
    try:
        booking = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
        if not booking:
            if request.method == 'POST':
                return jsonify({'success': False, 'message': 'Lab booking not found'}), 404
            flash("Lab booking not found.", "error")
            return redirect(url_for('inbox'))
        
        if request.method == 'GET':
            return render_template('lab_upload_reports.html', lab=booking)
        
        # Handle POST - File uploads
        if 'files' not in request.files or len(request.files.getlist('files')) == 0:
            return jsonify({'success': False, 'message': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        uploaded_files = []
        
        for file in files:
            if file and file.filename:
                # Validate file size (5MB max)
                if file.content_length and file.content_length > 5 * 1024 * 1024:
                    return jsonify({'success': False, 'message': f'File {file.filename} is too large (max 5MB)'}), 400
                
                # Validate file type
                allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg'}
                file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                if file_ext not in allowed_extensions:
                    return jsonify({'success': False, 'message': f'File type {file_ext} not allowed'}), 400
                
                # Save file
                filename = secure_filename(f"lab_report_{booking_id}_{uuid.uuid4().hex}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                uploaded_files.append({
                    'filename': filename,
                    'original_name': file.filename,
                    'uploaded_at': datetime.datetime.now()
                })
        
        # Update booking with reports
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {
                'status': 'Report Available',
                'report_submitted': True,
                'reports': uploaded_files,
                'reports_uploaded_at': datetime.datetime.now()
            }}
        )
        
        # Add to user's reports collection (for Health Records)
        for report in uploaded_files:
            reports_collection.insert_one({
                'user_id': session['user_id'],
                'name': f"{booking.get('test_name', 'Lab Test')} Report",
                'filename': report['filename'],
                'type': 'Lab Report',
                'date': datetime.datetime.now().strftime("%Y-%m-%d"),
                'booking_id': booking_id
            })
        
        return jsonify({'success': True, 'message': 'Reports uploaded successfully'}), 200
        
    except Exception as e:
        print(f"Error uploading lab reports: {e}")
        if request.method == 'POST':
            return jsonify({'success': False, 'message': str(e)}), 400
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('inbox'))

@app.route('/invoice/<invoice_id>')
@login_required
def view_invoice(invoice_id):
    """View invoice in beautiful HTML page."""
    invoice = invoices_collection.find_one({'_id': ObjectId(invoice_id), 'user_id': session['user_id']})
    if not invoice:
        flash("Invoice not found.", "error")
        return redirect(url_for('inbox'))
    
    # Get appointment details
    appointment = appointments_collection.find_one({'_id': ObjectId(invoice['appointment_id'])})
    user = users_collection.find_one({'_id': ObjectId(invoice['user_id'])})
    
    # Get doctor details if appointment exists
    doctor = None
    if appointment:
        doctor = doctors_collection.find_one({'name': appointment.get('doctor_name')})
    
    # Build invoice data for display
    invoice_data = {
        'invoice_id': invoice['invoice_id'],
        'created_at': invoice['created_at'].strftime('%Y-%m-%d %H:%M') if invoice.get('created_at') else 'N/A',
        'user_name': user.get('username', 'Patient') if user else 'Patient',
        'user_email': user.get('email', '') if user else '',
        'amount': invoice['amount'],
        'subtotal': invoice['amount'] / 1.1,  # Remove 10% tax
        'tax': invoice['amount'] - (invoice['amount'] / 1.1),
        'doctor_name': appointment.get('doctor_name', 'N/A') if appointment else 'N/A',
        'appointment_date': appointment.get('date', 'N/A') if appointment else 'N/A',
        'appointment_time': appointment.get('time', 'N/A') if appointment else 'N/A',
        'symptoms': appointment.get('symptoms', 'General Consultation') if appointment else 'General Consultation',
        'clinic_address': doctor.get('clinic_address', 'Online Consultation') if doctor else 'Online Consultation',
        'consultation_type': doctor.get('consultation_type', 'Online') if doctor else 'Online',
        'payment_status': 'PAID',
        'filename': invoice['filename']
    }
    
    return render_template('invoice_view.html', invoice=invoice_data, invoice_id=invoice_id)

@app.route('/invoice/<invoice_id>/download')
@login_required
def download_invoice(invoice_id):
    """Download invoice PDF."""
    invoice = invoices_collection.find_one({'_id': ObjectId(invoice_id), 'user_id': session['user_id']})
    if not invoice:
        flash("Invoice not found.", "error")
        return redirect(url_for('inbox'))
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], invoice['filename'])
    if not os.path.exists(file_path):
        flash("Invoice file not found.", "error")
        return redirect(url_for('inbox'))
    
    return send_file(file_path, as_attachment=True, download_name=f"invoice_{invoice['invoice_id']}.pdf")

@app.route('/book_lab_test/<test_name>', methods=['POST'])
@login_required
def book_lab_test(test_name):
    """Feature: Book a Lab Test (Login Required) - Redirect to checkout."""
    # Get hospital selection from form
    hospital_id = request.form.get('hospital_id', '')
    hospital_name = request.form.get('hospital_name', '')
    booking_date = request.form.get('booking_date', '')

    if not hospital_id:
        flash("Please select a hospital before booking.", "error")
        return redirect(url_for('view_lab_tests'))

    if not booking_date:
        flash("Please select a booking date.", "error")
        return redirect(url_for('view_lab_tests'))

    # Validate booking date - cannot be in the past
    try:
        date_obj = datetime.datetime.strptime(booking_date, "%Y-%m-%d").date()
        today = datetime.date.today()
        
        if date_obj < today:
            flash("❌ Booking date cannot be in the past.", "error")
            return redirect(url_for('view_lab_tests'))
        
        # NEW: Lab test bookings limited to 1 week from today
        one_week_later = today + datetime.timedelta(days=7)
        if date_obj > one_week_later:
            flash("❌ Lab tests can only be booked within 1 week from today.", "error")
            return redirect(url_for('view_lab_tests'))
    except ValueError:
        flash("Invalid date format.", "error")
        return redirect(url_for('view_lab_tests'))

    # Create a pending booking (payment happens only after hospital approval)
    lab_booking = {
        'user_id': session['user_id'],
        'test_name': test_name,
        'booking_date': booking_date,
        'date': datetime.datetime.now().strftime('%Y-%m-%d'),
        'status': 'Pending Approval',
        'payment_status': 'unpaid',
        'created_at': datetime.datetime.now(),
        'hospital_id': hospital_id,
        'hospital_name': hospital_name
    }
    result = lab_bookings_collection.insert_one(lab_booking)

    # Notify user
    try:
        notifications_collection.insert_one({
            'user_id': session['user_id'],
            'title': 'Lab Booking Submitted',
            'message': f"Your lab booking for {test_name} has been submitted and is awaiting hospital approval.",
            'created_at': datetime.datetime.now()
        })
    except Exception:
        pass

    flash("Lab booking submitted. Payment will be enabled after hospital approval.", "success")
    return redirect(url_for('inbox'))

@app.route('/inbox')
@login_required
def inbox():
    """Inbox: Appointments, Labs, Notifications."""
    user_id = session['user_id']
    appointments = list(appointments_collection.find({'user_id': user_id}))
    
    # Populate prescriptions for appointments if not embedded (Fix for existing data)
    for appt in appointments:
        if 'prescriptions' not in appt or not appt['prescriptions']:
            # Fetch from prescriptions collection using the appointment ID
            appt['prescriptions'] = list(prescriptions_collection.find({'appointment_id': str(appt['_id'])}))
            
        # Populate meals for appointments if not embedded
        if 'meals' not in appt or not appt['meals']:
            appt['meals'] = list(meals_collection.find({'user_id': user_id, 'doctor_name': appt.get('doctor_name')}))

    lab_bookings = list(lab_bookings_collection.find({'user_id': user_id}))

    # Auto-cancel unpaid appointments/labs if scheduled time has passed
    now = datetime.datetime.now()
    for appt in appointments:
        if appt.get('status') == 'Awaiting Payment' and appt.get('date') and appt.get('time'):
            try:
                appt_dt = datetime.datetime.strptime(f"{appt.get('date')} {appt.get('time')}", "%Y-%m-%d %H:%M")
                if appt_dt < now:
                    appointments_collection.update_one(
                        {'_id': appt['_id']},
                        {'$set': {
                            'status': 'Cancelled',
                            'cancelled_reason': 'Payment not completed before scheduled time',
                            'cancelled_at': now,
                            'cancelled_by': 'system'
                        }}
                    )
                    appt['status'] = 'Cancelled'
                    appt['cancelled_reason'] = 'Payment not completed before scheduled time'
                    try:
                        notifications_collection.insert_one({
                            'user_id': user_id,
                            'title': 'Appointment Cancelled',
                            'message': f"Your appointment with Dr. {appt.get('doctor_name')} was cancelled because payment was not completed before the scheduled time.",
                            'created_at': now
                        })
                    except Exception:
                        pass
            except Exception:
                pass

    for lb in lab_bookings:
        try:
            lb['_id_str'] = str(lb.get('_id'))
        except Exception:
            lb['_id_str'] = None
        if lb.get('status') in ['Awaiting Payment', 'Scheduled'] and lb.get('payment_status') != 'completed' and lb.get('scheduled_date') and lb.get('scheduled_time'):
            try:
                lab_dt = datetime.datetime.strptime(f"{lb.get('scheduled_date')} {lb.get('scheduled_time')}", "%Y-%m-%d %H:%M")
                if lab_dt < now:
                    lab_bookings_collection.update_one(
                        {'_id': lb['_id']},
                        {'$set': {
                            'status': 'Cancelled',
                            'cancelled_reason': 'Payment not completed before scheduled time',
                            'cancelled_at': now,
                            'cancelled_by': 'system'
                        }}
                    )
                    lb['status'] = 'Cancelled'
                    lb['cancelled_reason'] = 'Payment not completed before scheduled time'
                    try:
                        notifications_collection.insert_one({
                            'user_id': user_id,
                            'title': 'Lab Booking Cancelled',
                            'message': f"Your lab test {lb.get('test_name')} was cancelled because payment was not completed before the scheduled time.",
                            'created_at': now
                        })
                    except Exception:
                        pass
            except Exception:
                pass
    
    # Fetch Notifications (exclude expired ones)
    notifications = list(notifications_collection.find({
        'user_id': user_id,
        '$or': [
            {'expires_at': {'$exists': False}},
            {'expires_at': {'$gt': now}}
        ]
    }).sort('created_at', -1))
    
    # Fetch User Reports for linking
    user_reports = list(reports_collection.find({'user_id': user_id}))
    
    return render_template('inbox.html', 
                           appointments=appointments, 
                           lab_bookings=lab_bookings, 
                           notifications=notifications, 
                           user_reports=user_reports,
                           logged_in=True)


@app.route('/cancel/appointment/<appointment_id>', methods=['POST'])
@login_required
def cancel_appointment(appointment_id):
    """User cancels an appointment. Refund if payment completed."""
    appt = appointments_collection.find_one({'_id': ObjectId(appointment_id), 'user_id': session['user_id']})
    if not appt:
        flash('Appointment not found.', 'error')
        return redirect(url_for('inbox'))

    if appt.get('status') in ['Cancelled', 'Declined', 'Completed']:
        flash('Appointment cannot be cancelled.', 'info')
        return redirect(url_for('inbox'))

    refund_ok = False
    refund_info = None
    if appt.get('payment_status') == 'completed' and appt.get('payment_intent_id'):
        refund_ok, refund_info = _issue_refund(appt.get('payment_intent_id'))

    update_fields = {
        'status': 'Cancelled',
        'cancelled_reason': 'Cancelled by user',
        'cancelled_at': datetime.datetime.now(),
        'cancelled_by': 'user'
    }
    if refund_ok:
        update_fields['payment_status'] = 'refunded'
        update_fields['refund_id'] = refund_info.get('id') if isinstance(refund_info, dict) else None
        update_fields['refunded_at'] = datetime.datetime.now()
    elif appt.get('payment_status') == 'completed':
        update_fields['refund_status'] = 'failed'
        update_fields['refund_error'] = str(refund_info)

    appointments_collection.update_one({'_id': ObjectId(appointment_id)}, {'$set': update_fields})

    try:
        payments_collection.update_one(
            {'appointment_id': appointment_id},
            {'$set': {
                'status': 'refunded' if refund_ok else ('refund_failed' if appt.get('payment_status') == 'completed' else 'cancelled'),
                'refund_info': refund_info,
                'updated_at': datetime.datetime.now()
            }}
        )
    except Exception:
        pass

    try:
        notifications_collection.insert_one({
            'user_id': session['user_id'],
            'title': 'Appointment Cancelled',
            'message': f"Your appointment with Dr. {appt.get('doctor_name')} was cancelled. {('Refund initiated.' if refund_ok else 'Refund pending/failed.' if appt.get('payment_status') == 'completed' else '')}",
            'created_at': datetime.datetime.now()
        })
    except Exception:
        pass

    if refund_ok:
        flash('Appointment cancelled and refund initiated.', 'success')
    elif appt.get('payment_status') == 'completed':
        flash('Appointment cancelled. Refund failed or pending.', 'warning')
    else:
        flash('Appointment cancelled.', 'success')

    return redirect(url_for('inbox'))


@app.route('/cancel/lab/<booking_id>', methods=['POST'])
@login_required
def cancel_lab_booking(booking_id):
    """User cancels a lab booking. Refund if payment completed."""
    lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'user_id': session['user_id']})
    if not lb:
        flash('Lab booking not found.', 'error')
        return redirect(url_for('inbox'))

    if lb.get('status') in ['Cancelled', 'Rejected', 'Test Done']:
        flash('Lab booking cannot be cancelled.', 'info')
        return redirect(url_for('inbox'))

    refund_ok = False
    refund_info = None
    if lb.get('payment_status') == 'completed' and lb.get('payment_intent_id'):
        refund_ok, refund_info = _issue_refund(lb.get('payment_intent_id'))

    update_fields = {
        'status': 'Cancelled',
        'cancelled_reason': 'Cancelled by user',
        'cancelled_at': datetime.datetime.now(),
        'cancelled_by': 'user'
    }
    if refund_ok:
        update_fields['payment_status'] = 'refunded'
        update_fields['refund_id'] = refund_info.get('id') if isinstance(refund_info, dict) else None
        update_fields['refunded_at'] = datetime.datetime.now()
    elif lb.get('payment_status') == 'completed':
        update_fields['refund_status'] = 'failed'
        update_fields['refund_error'] = str(refund_info)

    lab_bookings_collection.update_one({'_id': ObjectId(booking_id)}, {'$set': update_fields})

    try:
        payments_collection.update_one(
            {'booking_id': booking_id},
            {'$set': {
                'status': 'refunded' if refund_ok else ('refund_failed' if lb.get('payment_status') == 'completed' else 'cancelled'),
                'refund_info': refund_info,
                'updated_at': datetime.datetime.now()
            }}
        )
    except Exception:
        pass

    try:
        notifications_collection.insert_one({
            'user_id': session['user_id'],
            'title': 'Lab Booking Cancelled',
            'message': f"Your lab test {lb.get('test_name')} was cancelled. {('Refund initiated.' if refund_ok else 'Refund pending/failed.' if lb.get('payment_status') == 'completed' else '')}",
            'created_at': datetime.datetime.now()
        })
    except Exception:
        pass

    if refund_ok:
        flash('Lab booking cancelled and refund initiated.', 'success')
    elif lb.get('payment_status') == 'completed':
        flash('Lab booking cancelled. Refund failed or pending.', 'warning')
    else:
        flash('Lab booking cancelled.', 'success')

    return redirect(url_for('inbox'))

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    
    # 1. Check User (Patient) - Uses Hashed Password
    user = users_collection.find_one({'email': email})
    if user and check_password_hash(user['password'], password):
        session['user_id'] = str(user['_id'])
        session['username'] = user['username']
        flash("Logged in successfully! Welcome back.", "success")
        return redirect(url_for('dashboard'))

    # 2. Check Doctor - Uses Plain Text Password (as requested)
    doctor = doctors_collection.find_one({'email': email})
    if doctor and doctor.get('password') == password:
        session['doctor_id'] = str(doctor['_id'])
        session['doctor_name'] = doctor['name']
        flash(f"Welcome Dr. {doctor['name']}", "success")
        return redirect(url_for('doctor_dashboard'))

    # 3. Check Hospital accounts (Atlas cluster)
    hospital = hospitals_collection.find_one({'email': email})
    if hospital and hospital.get('password') == password:
        session['hospital_id'] = str(hospital['_id'])
        session['hospital_name'] = hospital.get('name') or hospital.get('hospital_name') or hospital.get('email')
        flash(f"Welcome {session['hospital_name']}", "success")
        return redirect(url_for('hospital_dashboard'))

    flash("Login Failed! Please check your email or password.", "error")
    return redirect(url_for('auth_page'))

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role', 'patient') # Default to patient

    if role == 'doctor':
        # Doctor Registration
        if doctors_collection.find_one({'email': email}):
            flash("Doctor email already registered.", "error")
            return redirect(url_for('auth_page'))
        
        specialty = request.form.get('specialty', 'General Physician')
        # Note: Storing password as plain text to match existing login logic provided in context
        doctors_collection.insert_one({'name': username, 'email': email, 'password': password, 'specialty': specialty, 'availability_status': 'Available'})
        flash("Doctor registration successful! Please login.", "success")

    else:
        # Patient Registration
        if users_collection.find_one({'email': email}):
            flash("Email already registered. Please login.", "error")
            return redirect(url_for('auth_page'))

        hashed_password = generate_password_hash(password)
        users_collection.insert_one({'username': username, 'email': email, 'password': hashed_password})
        flash("Patient registration successful! Please login.", "success")

    return redirect(url_for('auth_page'))

@app.route('/logout')
def logout():
    """Logs the user out and clears the session."""
    session.clear()
    return redirect(url_for('auth_page'))

# ==========================================
# 3. PROTECTED ROUTES (Login Required)
# ==========================================

@app.route('/book_appointment', methods=['GET', 'POST'])
@login_required
def book_appointment():
    """Booking is only for logged-in users."""
    if request.method == 'POST':
        doctor_name = request.form.get('doctor_name')
        date = request.form.get('date')
        symptoms = request.form.get('symptoms')
        
        # Fetch doctor to check availability status
        doctor = doctors_collection.find_one({'name': doctor_name})
        if not doctor:
            flash("The selected doctor could not be found. Please choose a doctor from the Doctors page.", "error")
            return redirect(url_for('view_doctors'))
        
        # Validate Date: Cannot book in the past
        if date:
            booking_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
            today = datetime.date.today()
            
            if booking_date < today:
                flash("Please do not select a past date.", "error")
                doctors = list(doctors_collection.find({}, {'name': 1, 'specialty': 1, 'consultation_fees': 1, 'consultation_type': 1, 'clinic_address': 1}))
                return render_template('book_appointment.html', logged_in=True, doctors=doctors, selected_doctor=doctor_name, date=date, symptoms=symptoms)
            
            # NEW: Booking limited to 1 week from today
            one_week_later = today + datetime.timedelta(days=7)
            if booking_date > one_week_later:
                flash("❌ Appointments can only be booked within 1 week from today.", "error")
                doctors = list(doctors_collection.find({}, {'name': 1, 'specialty': 1, 'consultation_fees': 1, 'consultation_type': 1, 'clinic_address': 1}))
                return render_template('book_appointment.html', logged_in=True, doctors=doctors, selected_doctor=doctor_name, date=date, symptoms=symptoms)
        
        # Check doctor's availability status
        if doctor:
            status = doctor.get('availability_status', 'Available')
            
            # Check for On Leave status with date range
            if status == 'On Leave':
                leave_start = doctor.get('leave_start_date')
                leave_end = doctor.get('leave_end_date')
                
                if leave_start and leave_end:
                    try:
                        start_date = datetime.datetime.strptime(leave_start, "%Y-%m-%d").date()
                        end_date = datetime.datetime.strptime(leave_end, "%Y-%m-%d").date()
                        booking_date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
                        
                        if start_date <= booking_date_obj <= end_date:
                            return_date = (end_date + datetime.timedelta(days=1)).strftime("%B %d, %Y")
                            flash(f"❌ Dr. {doctor_name} is on leave until {leave_end}. Available from {return_date}.", "error")
                            doctors = list(doctors_collection.find({}, {'name': 1, 'specialty': 1, 'consultation_fees': 1, 'consultation_type': 1, 'clinic_address': 1}))
                            return render_template('book_appointment.html', logged_in=True, doctors=doctors, selected_doctor=doctor_name, date=date, symptoms=symptoms)
                    except ValueError:
                        pass
                else:
                    flash(f"❌ Dr. {doctor_name} is currently on leave. Appointments cannot be booked.", "error")
                    doctors = list(doctors_collection.find({}, {'name': 1, 'specialty': 1, 'consultation_fees': 1, 'consultation_type': 1, 'clinic_address': 1}))
                    return render_template('book_appointment.html', logged_in=True, doctors=doctors, selected_doctor=doctor_name, date=date, symptoms=symptoms)
        
        # Check Doctor's Daily Limit
        if doctor:
            limit = doctor.get('daily_patient_limit', 10)
            current_count = appointments_collection.count_documents({'doctor_name': doctor_name, 'date': date, 'status': {'$ne': 'Declined'}})
            if current_count >= limit:
                flash(f"Sorry, Dr. {doctor_name} is fully booked for {date} (Limit: {limit}). Please choose another date.", "error")
                doctors = list(doctors_collection.find({}, {'name': 1, 'specialty': 1, 'consultation_fees': 1, 'consultation_type': 1, 'clinic_address': 1}))
                return render_template('book_appointment.html', logged_in=True, doctors=doctors, selected_doctor=doctor_name, date=date, symptoms=symptoms)

        appointment = {
            "user_id": session['user_id'],
            "username": session['username'],
            "doctor_name": doctor_name,
            "date": date,
            "symptoms": symptoms,
            "status": "Pending",
            "payment_status": "pending",
            "created_at": datetime.datetime.now()
        }
        result = appointments_collection.insert_one(appointment)
        appointment_id = str(result.inserted_id)
        
        # Yellow Status: Busy - Show warning message along with success
        if doctor and doctor.get('availability_status') == 'Busy':
            flash("⚠ Appointment request sent, but Dr. " + doctor_name + " is currently busy. There may be delays in approval. Please wait for confirmation.", "warning")
        else:
            # Green Status: Available - Normal success message
            flash("✓ Appointment request sent! Please wait for doctor's approval.", "success")
        
        return redirect(url_for('inbox'))

    # Fetch doctors for the dropdown list
    selected_doctor = request.args.get('doctor')
    today = datetime.date.today()
    one_week_later = today + datetime.timedelta(days=7)
    doctors = list(doctors_collection.find({}, {'name': 1, 'specialty': 1, 'consultation_fees': 1, 'consultation_type': 1, 'clinic_address': 1}))
    return render_template('book_appointment.html', logged_in=True, doctors=doctors, selected_doctor=selected_doctor, today=today.isoformat(), max_date=one_week_later.isoformat())

@app.route('/notify_availability/<doctor_name>')
@login_required
def notify_availability(doctor_name):
    """Sends an email notification that the doctor is available."""
    user_id = session['user_id']
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    
    if user and user.get('email'):
        subject = f"Availability Alert: Dr. {doctor_name}"
        body = f"Hello {user.get('username', 'User')},\n\nGood news! Dr. {doctor_name} is now available for appointments.\n\nPlease log in to the Smart Health portal to book your slot immediately.\n\nBest Regards,\nSmart Health Team"
        
        try:
            send_email(user['email'], subject, body)
            flash(f"Notification email sent to {user['email']}!", "success")
        except Exception as e:
            flash(f"Failed to send email: {str(e)}", "error")
    else:
        flash("User email not found.", "error")
        
    return redirect(url_for('view_doctors'))

@app.route('/my_health_records')
@login_required
def health_records():
    """Health records: View Reports and Track Medicines."""
    user_id = session['user_id']
    
    # Fetch user details for profile
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    
    # Fetch real reports
    reports = list(reports_collection.find({'user_id': user_id}))
    
    # Fetch lab bookings (to show in reports section)
    lab_bookings = list(lab_bookings_collection.find({'user_id': user_id}))
    
    # Fetch real prescriptions
    prescriptions = list(prescriptions_collection.find({'user_id': user_id}).sort('date', -1))
    
    # Generate Schedule for each prescription
    for rx in prescriptions:
        try:
            duration = int(rx.get('duration', 0))
            history = rx.get('history', {}) # e.g., {'1': 'Taken', '2': 'Missed'}
            schedule = []
            
            for day in range(1, duration + 1):
                status = history.get(str(day), 'Pending')
                schedule.append({'day': day, 'status': status})
            
            rx['schedule'] = schedule
        except ValueError:
            rx['schedule'] = []
    
    return render_template('health_records.html', 
                           reports=reports, 
                           lab_bookings=lab_bookings,
                           medicines=prescriptions, 
                           user=user,
                           logged_in=True)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    """Updates patient's personal medical profile."""
    user_id = session['user_id']
    data = {
        'name': request.form.get('name'),
        'age': request.form.get('age'),
        'gender': request.form.get('gender'),
        'blood_group': request.form.get('blood_group'),
        'allergies': request.form.get('allergies'),
        'chronic_conditions': request.form.get('chronic_conditions')
    }
    users_collection.update_one({'_id': ObjectId(user_id)}, {'$set': data})
    flash("Medical profile updated successfully.", "success")
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/upload_report', methods=['POST'])
@login_required
def upload_report():
    """Centralized report upload."""
    user_id = session['user_id']
    file = request.files.get('file')
    name = request.form.get('report_name')
    appointment_id = request.form.get('appointment_id')
    
    if file and name:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        report_data = {
            'user_id': user_id,
            'name': name,
            'filename': filename,
            'type': 'Patient Upload',
            'date': datetime.datetime.now().strftime("%Y-%m-%d")
        }
        reports_collection.insert_one(report_data)
        
        # If uploaded from an appointment, link it
        if appointment_id:
            appointments_collection.update_one(
                {'_id': ObjectId(appointment_id)},
                {'$push': {'reports': report_data}}
            )
            
        flash("Report uploaded successfully. Doctors can now view it.", "success")
    else:
        flash("Please provide a file and report name.", "error")
        
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/link_reports', methods=['POST'])
@login_required
def link_reports():
    """Links existing reports to an appointment."""
    appointment_id = request.form.get('appointment_id')
    report_ids = request.form.getlist('report_ids')
    
    if appointment_id and report_ids:
        selected_reports = list(reports_collection.find({'_id': {'$in': [ObjectId(rid) for rid in report_ids]}}))
        
        count = 0
        for report in selected_reports:
            # Check if report is already linked to avoid duplicates
            exists = appointments_collection.find_one({
                '_id': ObjectId(appointment_id),
                'reports._id': report['_id']
            })
            
            if not exists:
                appointments_collection.update_one(
                    {'_id': ObjectId(appointment_id)},
                    {'$push': {'reports': report}}
                )
                count += 1
        
        flash(f"{count} reports shared with doctor.", "success" if count > 0 else "info")
    else:
        flash("No reports selected.", "warning")
        
    return redirect(url_for('inbox'))

@app.route('/update_medicine_status/<prescription_id>/<int:day>/<status>')
@login_required
def update_medicine_status(prescription_id, day, status):
    """Marks a medicine as Taken or Missed for a specific day."""
    user_id = session['user_id']
    
    # Update the history for the specific day
    prescriptions_collection.update_one(
        {'_id': ObjectId(prescription_id)},
        {'$set': {f'history.{day}': status}}
    )
    
    if status == 'Missed':
        # Create a Notification instead of an appointment
        rx = prescriptions_collection.find_one({'_id': ObjectId(prescription_id)})
        
        notification = {
            "user_id": user_id,
            "title": "Missed Dose Alert",
            "message": f"You missed Day {day} of {rx.get('medicine_name')}.",
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "created_at": datetime.datetime.now()
        }
        notifications_collection.insert_one(notification)
        
        flash(f"Missed dose recorded. Check notifications.", "warning")
    else:
        flash(f"Day {day} marked as taken.", "success")
        
    return redirect(url_for('health_records'))

@app.route('/pay_appointment/<appointment_id>', methods=['POST'])
@login_required
def pay_appointment(appointment_id):
    """Mock Payment Gateway."""
    # In a real app, verify payment here.
    appointments_collection.update_one(
        {'_id': ObjectId(appointment_id)},
        {'$set': {'status': 'Confirmed'}}
    )
    
    # Notify User
    # Create payment notification with expiry at appointment time if available
    try:
        appt = appointments_collection.find_one({'_id': ObjectId(appointment_id)})
    except Exception:
        appt = None
    notif = {
        "user_id": session['user_id'],
        "title": "Payment Successful",
        "message": "Your appointment is now confirmed. You can join the meeting.",
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "created_at": datetime.datetime.now()
    }
    try:
        if appt and appt.get('date') and appt.get('time'):
            appt_dt = datetime.datetime.strptime(f"{appt.get('date')} {appt.get('time')}", "%Y-%m-%d %H:%M")
            notif['expires_at'] = appt_dt
    except Exception:
        pass
    notifications_collection.insert_one(notif)
    
    flash("Payment successful! Appointment confirmed.", "success")
    return redirect(url_for('inbox'))

# ==========================================
# DOCTOR PORTAL ROUTES
# ==========================================

@app.route('/doctor/dashboard')
@doctor_required
def doctor_dashboard():
    """Doctor's main dashboard."""
    doctor_id = session['doctor_id']
    doctor = doctors_collection.find_one({'_id': ObjectId(doctor_id)})
    
    # Check Profile Completeness
    required_fields = ['qualification', 'experience_years', 'consultation_fees', 'clinic_address', 'image', 'consultation_type']
    profile_complete = all(doctor.get(field) for field in required_fields)
    
    # Fetch appointments for this doctor
    all_appointments = list(appointments_collection.find({'doctor_name': doctor['name']}))
    
    # Separate into Pending and Active (Confirmed/Completed)
    pending_appointments = [a for a in all_appointments if a.get('status') == 'Pending' or not a.get('status')]
    active_appointments = [a for a in all_appointments if a.get('status') in ['Accepted', 'Awaiting Payment', 'Confirmed', 'Completed']]
    
    return render_template('doctor_dashboard.html', 
                           doctor=doctor, 
                           profile_complete=profile_complete,
                           pending_appointments=pending_appointments,
                           active_appointments=active_appointments)

@app.route('/doctor/update_profile', methods=['POST'])
@doctor_required
def doctor_update_profile():
    """Handle Doctor Profile Update & Image Upload."""
    doctor_id = session['doctor_id']
    
    update_data = {
        'specialty': request.form.get('specialty'),
        'qualification': request.form.get('qualification'),
        'experience_years': int(request.form.get('experience_years')) if request.form.get('experience_years') else 0,
        'experience': f"{request.form.get('experience_years')}+ Yrs",
        'consultation_fees': int(request.form.get('consultation_fees')) if request.form.get('consultation_fees') else 0,
        'clinic_address': request.form.get('clinic_address'),
        'consultation_type': 'Online'
    }
    
    # Handle Image Upload
    file = request.files.get('image')
    if file and file.filename:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        # Save the path to be used in src attribute
        update_data['image'] = url_for('static', filename='uploads/' + filename)
        
    doctors_collection.update_one({'_id': ObjectId(doctor_id)}, {'$set': update_data})
    flash("Profile updated successfully!", "success")
    return redirect(url_for('doctor_dashboard'))
# ==========================================
# HOSPITAL DASHBOARD (Lab Management)
# ==========================================


@app.route('/hospital/dashboard')
@hospital_required
def hospital_dashboard():
    """Hospital dashboard hub - main navigation."""
    hosp_id = session.get('hospital_id')
    
    # Get all bookings for this hospital
    if hosp_id:
        all_bookings = list(lab_bookings_collection.find({'hospital_id': hosp_id}).sort('created_at', -1))
    else:
        all_bookings = []
    
    # Count bookings by status
    pending_approvals = [b for b in all_bookings if b.get('status') == 'Pending Approval']
    pending_payments = [b for b in all_bookings if b.get('status') in ['Awaiting Payment', 'Approved'] and b.get('payment_status') != 'completed']
    scheduled = [b for b in all_bookings if b.get('status') == 'Scheduled']
    reports_pending = [b for b in all_bookings if b.get('test_done') and not b.get('report_submitted')]
    
    stats = {
        'pending_approvals': len(pending_approvals),
        'pending_payments': len(pending_payments),
        'scheduled': len(scheduled),
        'reports_pending': len(reports_pending)
    }
    
    return render_template('hospital_dashboard.html', stats=stats, logged_in=True)


@app.route('/hospital/pending-approvals')
@hospital_required
def hospital_pending_approvals():
    """View pending lab bookings awaiting approval."""
    hosp_id = session.get('hospital_id')
    search_query = request.args.get('search', '').strip()
    
    if hosp_id:
        bookings = list(lab_bookings_collection.find({
            'hospital_id': hosp_id,
            'status': 'Pending Approval'
        }).sort('created_at', -1))
    else:
        bookings = []
    
    # Filter by search query (test name, patient name, date)
    if search_query:
        bookings = [b for b in bookings if 
            search_query.lower() in b.get('test_name', '').lower() or
            search_query.lower() in str(b.get('created_at', '')).lower()
        ]
    
    # Resolve user names and get test details
    for lb in bookings:
        try:
            user = users_collection.find_one({'_id': ObjectId(lb['user_id'])})
            lb['user_name'] = user.get('username') if user else 'Unknown'
            lb['user_email'] = user.get('email') if user else 'N/A'
        except Exception:
            lb['user_name'] = 'Unknown'
            lb['user_email'] = 'N/A'
        
        test = lab_tests_collection.find_one({'name': lb.get('test_name')})
        if test:
            lb['test_price'] = _get_lab_test_price(test)
            lb['test_category'] = test.get('category', 'General')
        else:
            lb['test_price'] = 0
            lb['test_category'] = 'General'
        
        lb['_id_str'] = str(lb.get('_id'))
    
    return render_template('hospital_pending_approvals.html', bookings=bookings, logged_in=True, search_query=search_query)


@app.route('/hospital/pending-payments')
@hospital_required
def hospital_pending_payments():
    """View approved bookings awaiting payment."""
    hosp_id = session.get('hospital_id')
    search_query = request.args.get('search', '').strip()
    
    if hosp_id:
        bookings = list(lab_bookings_collection.find({
            'hospital_id': hosp_id,
            'status': {'$in': ['Awaiting Payment', 'Approved']},
            'payment_status': {'$ne': 'completed'}
        }).sort('created_at', -1))
    else:
        bookings = []
    
    # Filter by search query
    if search_query:
        bookings = [b for b in bookings if 
            search_query.lower() in b.get('test_name', '').lower() or
            search_query.lower() in str(b.get('created_at', '')).lower()
        ]
    
    # Resolve user names and get test details
    for lb in bookings:
        try:
            user = users_collection.find_one({'_id': ObjectId(lb['user_id'])})
            lb['user_name'] = user.get('username') if user else 'Unknown'
            lb['user_email'] = user.get('email') if user else 'N/A'
        except Exception:
            lb['user_name'] = 'Unknown'
            lb['user_email'] = 'N/A'
        
        test = lab_tests_collection.find_one({'name': lb.get('test_name')})
        if test:
            lb['test_price'] = _get_lab_test_price(test)
            lb['test_category'] = test.get('category', 'General')
        else:
            lb['test_price'] = 0
            lb['test_category'] = 'General'
        
        lb['_id_str'] = str(lb.get('_id'))
    
    return render_template('hospital_pending_payments.html', bookings=bookings, logged_in=True, search_query=search_query)


@app.route('/hospital/scheduled')
@hospital_required
def hospital_scheduled():
    """View scheduled lab appointments."""
    hosp_id = session.get('hospital_id')
    search_query = request.args.get('search', '').strip()
    
    if hosp_id:
        bookings = list(lab_bookings_collection.find({
            'hospital_id': hosp_id,
            'status': 'Scheduled'
        }).sort('scheduled_date', 1))
    else:
        bookings = []
    
    # Filter by search query
    if search_query:
        bookings = [b for b in bookings if 
            search_query.lower() in b.get('test_name', '').lower() or
            search_query.lower() in str(b.get('scheduled_date', '')).lower() or
            search_query.lower() in str(b.get('scheduled_time', '')).lower()
        ]
    
    # Resolve user names and get test details
    for lb in bookings:
        try:
            user = users_collection.find_one({'_id': ObjectId(lb['user_id'])})
            lb['user_name'] = user.get('username') if user else 'Unknown'
            lb['user_email'] = user.get('email') if user else 'N/A'
        except Exception:
            lb['user_name'] = 'Unknown'
            lb['user_email'] = 'N/A'
        
        test = lab_tests_collection.find_one({'name': lb.get('test_name')})
        if test:
            lb['test_price'] = _get_lab_test_price(test)
            lb['test_category'] = test.get('category', 'General')
        else:
            lb['test_price'] = 0
            lb['test_category'] = 'General'
        
        lb['_id_str'] = str(lb.get('_id'))
    
    return render_template('hospital_scheduled.html', bookings=bookings, logged_in=True, search_query=search_query)


@app.route('/hospital/reports')
@hospital_required
def hospital_reports():
    """View scheduled appointments ready for report submission."""
    hosp_id = session.get('hospital_id')
    search_query = request.args.get('search', '').strip()
    
    if hosp_id:
        bookings = list(lab_bookings_collection.find({
            'hospital_id': hosp_id,
            'test_done': True,
            'report_submitted': {'$ne': True}
        }).sort('scheduled_date', 1))
    else:
        bookings = []
    
    # Filter by search query
    if search_query:
        bookings = [b for b in bookings if 
            search_query.lower() in b.get('test_name', '').lower() or
            search_query.lower() in str(b.get('scheduled_date', '')).lower()
        ]
    
    # Resolve user names and get test details
    for lb in bookings:
        try:
            user = users_collection.find_one({'_id': ObjectId(lb['user_id'])})
            lb['user_name'] = user.get('username') if user else 'Unknown'
            lb['user_email'] = user.get('email') if user else 'N/A'
        except Exception:
            lb['user_name'] = 'Unknown'
            lb['user_email'] = 'N/A'
        
        test = lab_tests_collection.find_one({'name': lb.get('test_name')})
        if test:
            lb['test_price'] = _get_lab_test_price(test)
            lb['test_category'] = test.get('category', 'General')
        else:
            lb['test_price'] = 0
            lb['test_category'] = 'General'
        
        lb['_id_str'] = str(lb.get('_id'))
    
    return render_template('hospital_reports.html', bookings=bookings, logged_in=True, search_query=search_query)


@app.route('/hospital/history')
@hospital_required
def hospital_history():
    """Hospital history - shows all past lab bookings, completed tests, and reports submitted."""
    hosp_id = session.get('hospital_id')
    
    if hosp_id:
        # Get all bookings for this hospital (including completed ones)
        all_bookings = list(lab_bookings_collection.find({'hospital_id': hosp_id}).sort('created_at', -1))
    else:
        all_bookings = []
    
    # Separate into completed and active
    completed_bookings = [b for b in all_bookings if b.get('report_submitted') or b.get('status') in ['Report Available', 'Completed']]
    rejected_bookings = [b for b in all_bookings if b.get('status') == 'Rejected']
    
    # Resolve user names and test details
    for lb in completed_bookings + rejected_bookings:
        try:
            user = users_collection.find_one({'_id': ObjectId(lb['user_id'])})
            lb['user_name'] = user.get('username') if user else 'Unknown'
            lb['user_email'] = user.get('email') if user else 'N/A'
        except Exception:
            lb['user_name'] = 'Unknown'
            lb['user_email'] = 'N/A'
        
        # Get test details
        test = lab_tests_collection.find_one({'name': lb.get('test_name')})
        if test:
            lb['test_price'] = _get_lab_test_price(test)
            lb['test_category'] = test.get('category', 'General')
        else:
            lb['test_price'] = 0
            lb['test_category'] = 'General'
        
        lb['_id_str'] = str(lb.get('_id'))
    
    return render_template('hospital_history.html', 
                          completed_bookings=completed_bookings,
                          rejected_bookings=rejected_bookings,
                          logged_in=True)


@app.route('/hospital/lab/<booking_id>/approve', methods=['POST', 'GET'])
@hospital_required
def hospital_approve_lab(booking_id):
    """Approve a lab booking and set appointment date/time."""
    try:
        lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
        if not lb:
            flash('Lab booking not found.', 'error')
            return redirect(url_for('hospital_dashboard'))
        
        # Use the booking_date selected by user, or today if not available
        booking_date = lb.get('booking_date', datetime.datetime.now().strftime('%Y-%m-%d'))
        
        # If GET request, show approval form with time slot selection (date is the booking_date)
        if request.method == 'GET':
            return render_template('hospital_approve_lab_modal.html', booking=lb, booking_id=booking_id, fixed_date=booking_date)
        
        # If POST request, process approval with booking_date and selected time
        scheduled_time = request.form.get('scheduled_time')
        scheduled_date = booking_date  # Use the booking_date selected by user
        
        if not scheduled_time:
            flash('Please select a time slot for the test.', 'error')
            fixed_date = datetime.datetime.now().strftime('%Y-%m-%d')
            return render_template('hospital_approve_lab_modal.html', booking=lb, booking_id=booking_id, fixed_date=fixed_date)
        
        # Check daily limit
        if _check_daily_test_limit(lb.get('hospital_id'), scheduled_date):
            flash('⚠️ Cannot schedule: Hospital already has 5 tests for today. Please try again tomorrow.', 'error')
            fixed_date = datetime.datetime.now().strftime('%Y-%m-%d')
            return render_template('hospital_approve_lab_modal.html', booking=lb, booking_id=booking_id, fixed_date=fixed_date)
        
        # Update booking status to approved with scheduled time
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)}, 
            {'$set': {
                'status': 'Awaiting Payment',
                'scheduled_date': scheduled_date,
                'scheduled_time': scheduled_time,
                'approved_at': datetime.datetime.now(),
                'approved_by': session.get('hospital_name', 'Hospital'),
                'schedule_pending_payment': True
            }}
        )
        
        # Notify user that booking is approved
        user = users_collection.find_one({'_id': ObjectId(lb['user_id'])})
        
        # Send approval email with payment details
        try:
            test = lab_tests_collection.find_one({'name': lb.get('test_name')})
            test_cost = _get_lab_test_price(test)
            
            approval_subject = f"✅ Lab Test Approved & Scheduled - {lb.get('test_name')} - Ready for Payment"
            
            approval_body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                        <h2 style="color: #16a34a; text-align: center;">✅ Your Lab Test has been Approved & Scheduled!</h2>
                        
                        <p>Dear {user.get('username', 'Patient')},</p>
                        
                        <p>Great news! Your lab test request has been <strong>APPROVED</strong> by {session.get('hospital_name', 'the hospital')} and <strong>SCHEDULED</strong> for the date and time below. Complete payment to confirm.</p>
                        
                        <!-- TEST DETAILS SECTION -->
                        <div style="background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%); padding: 20px; border-left: 4px solid #0284c7; margin: 20px 0; border-radius: 6px;">
                            <h3 style="color: #0284c7; margin-top: 0;">🔬 Lab Test Details</h3>
                            <table style="width: 100%; border-collapse: collapse;">
                                <tr>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Test Name:</strong></td>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{lb.get('test_name', 'N/A')}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Hospital/Lab:</strong></td>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{lb.get('hospital_name', 'Standard Lab')}</td>
                                </tr>
                                <tr>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>📅 Scheduled Date:</strong></td>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><span style="background: #dbeafe; padding: 4px 8px; border-radius: 4px;">{scheduled_date}</span></td>
                                </tr>
                                <tr>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>🕐 Scheduled Time:</strong></td>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><span style="background: #dbeafe; padding: 4px 8px; border-radius: 4px;">{scheduled_time}</span></td>
                                </tr>
                                <tr>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>💰 Test Cost:</strong></td>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong style="color: #16a34a; font-size: 16px;">₹{test_cost}</strong></td>
                                </tr>
                                <tr>
                                    <td style="padding: 10px 0;"><strong>Status:</strong></td>
                                    <td style="padding: 10px 0;"><span style="background: #dcfce7; color: #16a34a; padding: 4px 8px; border-radius: 4px; font-weight: bold;">APPROVED & SCHEDULED ✓</span></td>
                                </tr>
                            </table>
                        </div>
                        
                        <!-- PAYMENT SECTION -->
                        <div style="background: linear-gradient(135deg, #fef3c7 0%, #fef08a 100%); padding: 20px; border-left: 4px solid #f59e0b; margin: 20px 0; border-radius: 6px;">
                            <h3 style="color: #d97706; margin-top: 0;">💳 Next: Complete Your Payment</h3>
                            <p style="color: #92400e; margin: 10px 0;">Your lab test has been approved and scheduled! Complete the payment below to confirm your appointment.</p>
                            <table style="width: 100%; border-collapse: collapse;">
                                <tr>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #fed7aa;"><strong>Amount Due:</strong></td>
                                    <td style="padding: 10px 0; border-bottom: 1px solid #fed7aa; text-align: right;"><strong style="font-size: 18px;">₹{test_cost}</strong></td>
                                </tr>
                                <tr>
                                    <td style="padding: 10px 0;"><strong>Tax (10%):</strong></td>
                                    <td style="padding: 10px 0; text-align: right;">₹{test_cost * 0.10:.2f}</td>
                                </tr>
                                <tr style="background: #fbbf24;">
                                    <td style="padding: 12px; font-weight: bold; color: white;">Total to Pay:</td>
                                    <td style="padding: 12px; text-align: right; font-weight: bold; color: white; font-size: 18px;">₹{test_cost + (test_cost * 0.10):.2f}</td>
                                </tr>
                            </table>
                        </div>
                        
                        <!-- CALL TO ACTION -->
                        <div style="text-align: center; margin: 25px 0;">
                            <a href="{request.url_root.rstrip('/')}/checkout/lab?booking_id={str(booking_id)}" style="display: inline-block; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: white; padding: 15px 40px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);">💳 Proceed to Payment Now</a>
                        </div>
                        
                        <!-- IMPORTANT NOTES -->
                        <div style="background-color: #fffbeb; padding: 12px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #f59e0b;">
                            <p style="margin: 0; color: #92400e;"><strong>📌 Important:</strong> Your test is scheduled on the date and time above. Please arrive 10 minutes early on the day of the test.</p>
                        </div>
                        
                        <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                        
                        <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
                            Best Regards,<br>
                            <strong>Smart Health Management System</strong><br>
                            <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a>
                        </p>
                    </div>
                </body>
            </html>
            """
            
            email_service.send_email(
                user.get('email'),
                approval_subject,
                approval_body,
                is_html=True
            )
            print(f"✅ Approval email sent to {user.get('email')}")
        except Exception as e:
            print(f'⚠️ Error sending approval email: {e}')
        
        try:
            notifications_collection.insert_one({
                'user_id': lb['user_id'],
                'title': '✅ Lab Booking Approved!',
                'message': f"Great! Your {lb.get('test_name')} booking at {lb.get('hospital_name', 'our lab')} has been APPROVED. Proceed to payment to confirm your appointment.",
                'created_at': datetime.datetime.now(),
                'booking_id': booking_id,
                'type': 'booking_approved'
            })
        except Exception as e:
            print(f'Error sending approval notification: {e}')
        
        flash('✅ Lab booking approved! User will now proceed to payment.', 'success')
        return redirect(url_for('hospital_dashboard'))
    
    except Exception as e:
        print(f'Error approving lab booking: {e}')
        flash('Error approving booking.', 'error')
        return redirect(url_for('hospital_dashboard'))


@app.route('/hospital/lab/booked-slots', methods=['GET'])
@hospital_required
def get_booked_slots():
    """Get list of booked time slots for a given date and hospital."""
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({'booked_slots': []}), 400
        
        hospital_id = session.get('hospital_id')
        booked_times = _get_booked_slots(hospital_id, date)
        
        return jsonify({'booked_slots': booked_times}), 200
    except Exception as e:
        print(f'Error fetching booked slots: {e}')
        return jsonify({'booked_slots': [], 'error': str(e)}), 500


@app.route('/doctor/booked-slots', methods=['GET'])
@doctor_required
def get_booked_doctor_slots():
    """Get list of booked time slots for doctor appointments on a given date."""
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({'booked_slots': []}), 400
        
        doctor_id = session.get('doctor_id')
        # Find appointments scheduled for this doctor on the given date
        booked_appointments = appointments_collection.find({
            'doctor_id': doctor_id,
            'scheduled_date': date,
            'scheduled_time': {'$exists': True, '$ne': None},
            'status': {'$in': ['Accepted', 'Completed']}
        })
        booked_times = [appt.get('scheduled_time') for appt in booked_appointments if appt.get('scheduled_time')]
        
        return jsonify({'booked_slots': booked_times}), 200
    except Exception as e:
        print(f'Error fetching booked doctor slots: {e}')
        return jsonify({'booked_slots': [], 'error': str(e)}), 500


@app.route('/hospital/lab/<booking_id>/reject', methods=['POST'])
@hospital_required
def hospital_reject_lab(booking_id):
    reason = request.form.get('reason', 'Not specified')
    lab_bookings_collection.update_one({'_id': ObjectId(booking_id)}, {'$set': {'status': 'Rejected', 'rejected_reason': reason}})
    lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
    try:
        notifications_collection.insert_one({
            'user_id': lb['user_id'],
            'title': 'Lab Booking Rejected',
            'message': f"Your lab booking for {lb.get('test_name')} was rejected. Reason: {reason}",
            'created_at': datetime.datetime.now()
        })
    except Exception:
        pass
    flash('Lab booking rejected.', 'success')
    return redirect(url_for('hospital_dashboard'))


@app.route('/hospital/lab/<booking_id>/set_time', methods=['POST'])
@hospital_required
def hospital_set_lab_time(booking_id):
    """Set lab appointment time. Show time to user after payment."""
    try:
        date = request.form.get('date')
        time_val = request.form.get('time')
        
        lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
        if not lb:
            flash('Lab booking not found.', 'error')
            return redirect(url_for('hospital_dashboard'))
        
        # Update booking with time (allow scheduling before payment)
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)}, 
            {'$set': {
                'status': 'Scheduled',
                'scheduled_date': date,
                'scheduled_time': time_val,
                'scheduled_at': datetime.datetime.now(),
                'schedule_pending_payment': lb.get('payment_status') != 'completed'
            }}
        )

        # Notify user only after payment is completed
        if lb.get('payment_status') == 'completed':
            try:
                notifications_collection.insert_one({
                    'user_id': lb['user_id'],
                    'title': '📅 Appointment Scheduled!',
                    'message': f"Your {lb.get('test_name')} is scheduled on {date} at {time_val} at {lb.get('hospital_name', 'lab')}. Your payment has been received. See you then!",
                    'created_at': datetime.datetime.now(),
                    'booking_id': booking_id,
                    'type': 'appointment_scheduled'
                })
            except Exception as e:
                print(f'Error sending schedule notification: {e}')
            flash(f'✅ Time scheduled and user notified: {date} at {time_val}', 'success')
        else:
            flash('✅ Time scheduled. User will see the date/time after payment.', 'success')
    except Exception as e:
        print(f'Error setting lab time: {e}')
        flash('Error setting time.', 'error')
    
    return redirect(url_for('hospital_dashboard'))


@app.route('/hospital/lab/<booking_id>/cancel', methods=['POST'])
@hospital_required
def hospital_cancel_lab(booking_id):
    """Hospital cancels lab test and issues refund if paid."""
    reason = request.form.get('reason', 'Cancelled by hospital')
    hosp_id = session.get('hospital_id')
    lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id), 'hospital_id': hosp_id})
    if not lb:
        flash('Lab booking not found.', 'error')
        return redirect(url_for('hospital_scheduled'))

    if lb.get('status') in ['Cancelled', 'Rejected']:
        flash('Booking is already cancelled.', 'info')
        return redirect(url_for('hospital_scheduled'))

    refund_ok = False
    refund_info = None
    if lb.get('payment_status') == 'completed' and lb.get('payment_intent_id'):
        refund_ok, refund_info = _issue_refund(lb.get('payment_intent_id'))

    update_fields = {
        'status': 'Cancelled',
        'cancelled_reason': reason,
        'cancelled_at': datetime.datetime.now(),
        'cancelled_by': 'hospital'
    }
    if refund_ok:
        update_fields['payment_status'] = 'refunded'
        update_fields['refund_id'] = refund_info.get('id') if isinstance(refund_info, dict) else None
        update_fields['refunded_at'] = datetime.datetime.now()
    elif lb.get('payment_status') == 'completed':
        update_fields['refund_status'] = 'failed'
        update_fields['refund_error'] = str(refund_info)

    lab_bookings_collection.update_one({'_id': ObjectId(booking_id)}, {'$set': update_fields})

    # Update payment record
    try:
        payments_collection.update_one(
            {'booking_id': booking_id},
            {'$set': {
                'status': 'refunded' if refund_ok else ('refund_failed' if lb.get('payment_status') == 'completed' else 'cancelled'),
                'refund_info': refund_info,
                'updated_at': datetime.datetime.now()
            }}
        )
    except Exception:
        pass

    # Notify user
    try:
        notifications_collection.insert_one({
            'user_id': lb['user_id'],
            'title': 'Lab Booking Cancelled',
            'message': f"Your lab test {lb.get('test_name')} was cancelled by the hospital. {('Refund initiated.' if refund_ok else 'Refund pending/failed.' if lb.get('payment_status') == 'completed' else '')}",
            'created_at': datetime.datetime.now()
        })
    except Exception:
        pass

    if refund_ok:
        flash('Lab test cancelled and refund initiated.', 'success')
    elif lb.get('payment_status') == 'completed':
        flash('Lab test cancelled. Refund failed or pending.', 'warning')
    else:
        flash('Lab test cancelled.', 'success')

    return redirect(url_for('hospital_scheduled'))


@app.route('/hospital/lab/<booking_id>/mark_test_done', methods=['POST'])
@hospital_required
def hospital_mark_test_done(booking_id):
    """Mark that the lab test has been performed and the hospital can upload reports."""
    try:
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)},
            {'$set': {'test_done': True, 'status': 'Report Pending'}}
        )
        lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
        try:
            notifications_collection.insert_one({
                'user_id': lb['user_id'],
                'title': 'Lab Test Completed',
                'message': f"Your lab test {lb.get('test_name')} has been completed by the lab. Report will be uploaded shortly.",
                'created_at': datetime.datetime.now()
            })
        except Exception:
            pass
        flash('Marked test as done; you may now upload the report.', 'success')
    except Exception as e:
        print('Error marking test done:', e)
        flash('Failed to mark test done.', 'error')
    return redirect(url_for('hospital_reports'))


@app.route('/hospital/lab/<booking_id>/upload_report', methods=['POST'])
@hospital_required
def hospital_upload_report(booking_id):
    """Upload a lab report file, save to reports collection and email the patient."""
    # Ensure the lab booking exists and test has been performed
    lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
    if not lb:
        flash('Lab booking not found.', 'error')
        return redirect(url_for('hospital_dashboard'))
    if not lb.get('test_done'):
        flash('Cannot upload report: lab test not marked done yet.', 'error')
        return redirect(url_for('hospital_dashboard'))

    file = request.files.get('report_file')
    if not file or not file.filename:
        flash('No file provided.', 'error')
        return redirect(url_for('hospital_dashboard'))

    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)

    # Insert into reports collection
    report_record = {
        'user_id': None,
        'booking_id': booking_id,
        'name': 'Lab Report',
        'filename': filename,
        'type': 'Lab Report',
        'date': datetime.datetime.now().strftime("%Y-%m-%d")
    }
    try:
        lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
        report_record['user_id'] = lb.get('user_id')
        report_record['name'] = f"{lb.get('test_name', 'Lab Test')} Report"
        reports_collection.insert_one(report_record)
        # Update booking status to completed and mark as reported
        lab_bookings_collection.update_one(
            {'_id': ObjectId(booking_id)}, 
            {'$set': {
                'status': 'Report Available',
                'report_submitted': True,
                'report_submitted_at': datetime.datetime.now()
            }}
        )
        # Send email with attachment
        user = users_collection.find_one({'_id': ObjectId(lb.get('user_id'))})
        if user and user.get('email'):
            subject = f"Your Lab Report: {lb.get('test_name')} ✅"
            body = f"Dear {user.get('username', '')},\n\nYour lab report for {lb.get('test_name')} is ready! Please find the attached report.\n\n✓ Test: {lb.get('test_name')}\n✓ Hospital: {lb.get('hospital_name', 'Lab')}\n✓ Date: {lb.get('scheduled_date', 'N/A')}\n\nRegards,\nHospital Lab Team"
            # send as HTML with attachment
            email_service.send_email(user.get('email'), subject, body, is_html=False, attachments=[save_path])
        
        # Notify user
        try:
            notifications_collection.insert_one({
                'user_id': lb['user_id'],
                'title': '📊 Your Lab Report is Ready!',
                'message': f"Your {lb.get('test_name')} report from {lb.get('hospital_name', 'lab')} is ready. Check your email for the report attachment.",
                'created_at': datetime.datetime.now(),
                'booking_id': booking_id,
                'type': 'report_ready'
            })
        except Exception as e:
            print(f'Error sending report notification: {e}')
        
        flash('✅ Report uploaded and emailed to patient. Entry removed from active list.', 'success')
    except Exception as e:
        print('Error saving report:', e)
        flash('Failed to save or send report.', 'error')

    return redirect(url_for('hospital_dashboard'))


@app.route('/hospital/lab/<booking_id>/mark_paid', methods=['POST'])
@hospital_required
def hospital_mark_paid(booking_id):
    """Manually mark a lab booking as paid/completed by hospital staff."""
    try:
        lab_bookings_collection.update_one({'_id': ObjectId(booking_id)}, {'$set': {'payment_status': 'completed', 'status': 'Completed', 'completed_at': datetime.datetime.now()}})
        lb = lab_bookings_collection.find_one({'_id': ObjectId(booking_id)})
        # notify user
        try:
            notifications_collection.insert_one({
                'user_id': lb['user_id'],
                'title': 'Payment Received',
                'message': f"We received payment for your lab test {lb.get('test_name')}. Your appointment is confirmed.",
                'created_at': datetime.datetime.now()
            })
        except Exception:
            pass
        flash('Marked as paid and completed.', 'success')
    except Exception as e:
        print('Error marking paid:', e)
        flash('Failed to mark payment.', 'error')
    return redirect(url_for('hospital_dashboard'))

@app.route('/doctor/appointment/<appointment_id>/accept', methods=['POST'])
@doctor_required
def accept_appointment(appointment_id):
    """Quickly accept a pending appointment."""
    # Enforce Profile Completeness
    doctor = doctors_collection.find_one({'_id': ObjectId(session['doctor_id'])})
    required_fields = ['qualification', 'experience_years', 'consultation_fees', 'clinic_address', 'image', 'consultation_type']
    if not all(doctor.get(field) for field in required_fields):
        flash("You must complete your profile (Image, Fees, Address, etc.) before accepting appointments.", "error")
        return redirect(url_for('doctor_dashboard'))
    
    # Get scheduled time if provided
    scheduled_time = request.form.get('scheduled_time')
    
    update_fields = {'status': 'Accepted'}
    if scheduled_time:
        update_fields['time'] = scheduled_time
        update_fields['scheduled_date'] = datetime.datetime.now().strftime('%Y-%m-%d')
    
    appointments_collection.update_one({'_id': ObjectId(appointment_id)}, {'$set': update_fields})
    flash("Please set a time and meeting link to confirm the appointment.", "info")
    return redirect(url_for('manage_appointment', appointment_id=appointment_id))

@app.route('/doctor/cancel_status', methods=['POST'])
@doctor_required
def cancel_doctor_status():
    """Cancel status - revert to Available."""
    doctor_id = session['doctor_id']
    update_data = {
        'availability_status': 'Available',
        'busy_start_time': None,
        'busy_end_time': None,
        'leave_start_date': None,
        'leave_end_date': None
    }
    doctors_collection.update_one({'_id': ObjectId(doctor_id)}, {'$set': update_data})
    flash("Status cancelled. You are now Available.", "success")
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/appointment/<appointment_id>/decline', methods=['POST'])
@doctor_required
def decline_appointment(appointment_id):
    """Decline a pending appointment with a reason."""
    reason = request.form.get('reason')
    if not reason:
        flash("A reason is required to decline an appointment.", "error")
        return redirect(url_for('doctor_dashboard'))

    appointments_collection.update_one(
        {'_id': ObjectId(appointment_id)},
        {'$set': {'status': 'Declined', 'decline_reason': reason}}
    )
    
    # Instead of sending email before payment, create an in-app notification only.
    try:
        appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id)})
        if appointment:
            user = users_collection.find_one({'_id': ObjectId(appointment['user_id'])})
            if user:
                notif = {
                    'user_id': appointment['user_id'],
                    'title': 'Appointment Update',
                    'message': f"Dr. {session['doctor_name']} declined your appointment for {appointment.get('date')}. Reason: {reason}",
                    'time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    'created_at': datetime.datetime.now()
                }
                try:
                    if appointment.get('date') and appointment.get('time'):
                        appt_dt = datetime.datetime.strptime(f"{appointment.get('date')} {appointment.get('time')}", "%Y-%m-%d %H:%M")
                        notif['expires_at'] = appt_dt
                except Exception:
                    pass
                notifications_collection.insert_one(notif)
    except Exception as e:
        print(f"Could not create decline notification: {e}")
        
    flash("Appointment declined and message sent to the patient.", "success")
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/status', methods=['POST'])
@doctor_required
def update_doctor_status():
    """Toggle availability: Available, Busy, On Leave - with duration support."""
    status = request.form.get('status')
    doctor_id = session['doctor_id']
    
    update_data = {'availability_status': status}
    
    # Handle On Leave - add start and end dates
    if status == 'On Leave':
        leave_start = request.form.get('leave_start_date')
        leave_end = request.form.get('leave_end_date')
        
        if leave_start and leave_end:
            update_data['leave_start_date'] = leave_start
            update_data['leave_end_date'] = leave_end
            message = f"Status updated to On Leave (until {leave_end})"
        else:
            message = "Status updated to On Leave"
    
    # Handle Busy - add start and end times
    elif status == 'Busy':
        busy_start = request.form.get('busy_start_time')
        busy_end = request.form.get('busy_end_time')
        
        if busy_start and busy_end:
            update_data['busy_start_time'] = busy_start
            update_data['busy_end_time'] = busy_end
            message = f"Status updated to Busy ({busy_start} - {busy_end})"
        else:
            message = "Status updated to Busy"
    
    # Handle Available - clear all duration fields
    else:
        update_data['busy_start_time'] = None
        update_data['busy_end_time'] = None
        update_data['leave_start_date'] = None
        update_data['leave_end_date'] = None
        message = "Status updated to Available"
    
    doctors_collection.update_one({'_id': ObjectId(doctor_id)}, {'$set': update_data})
    flash(message, "success")
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/patient/<user_id>', methods=['GET', 'POST'])
@doctor_required
def doctor_patient_view(user_id):
    """View patient reports and assign meals."""
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    
    if request.method == 'POST':
        # Create Meal Plan
        meal_content = request.form.get('meal_plan')
        if meal_content:
            meals_collection.insert_one({
                'user_id': user_id,
                'doctor_id': session['doctor_id'],
                'meal_plan': meal_content,
                'created_at': datetime.datetime.now(),
                'doctor_name': session['doctor_name']
            })
            flash("Meal plan assigned successfully!", "success")
            return redirect(url_for('doctor_patient_view', user_id=user_id))

    # Fetch Reports uploaded by user
    reports = list(reports_collection.find({'user_id': user_id}))
    # Fetch previous meals assigned
    meals = list(meals_collection.find({'user_id': user_id}))
    
    return render_template('doctor_patient_view.html', user=user, reports=reports, meals=meals)

@app.route('/doctor/medicines/search')
@doctor_required
def search_doctor_medicines():
    query = request.args.get('q', '').strip().lower()
    if len(query) < 2:
        return jsonify([])

    matches = [
        medicine for medicine in MEDICINE_OPTIONS
        if query in medicine['name'].lower()
    ][:50]
    return jsonify(matches)


@app.route('/doctor/appointment/<appointment_id>', methods=['GET', 'POST'])
@doctor_required
def manage_appointment(appointment_id):
    """
    Comprehensive Appointment Management for Doctors:
    - Set Time & Status
    - Online Meeting Link
    - View Reports
    - Prescribe Medicines
    - Assign Meals
    """
    appointment = appointments_collection.find_one({'_id': ObjectId(appointment_id)})
    if not appointment:
        flash("Appointment not found.", "error")
        return redirect(url_for('doctor_dashboard'))
    
    user_id = appointment['user_id']
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    
    # Fetch doctor details to determine consultation type (Online vs In-Clinic)
    doctor = doctors_collection.find_one({'_id': ObjectId(session['doctor_id'])})
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_appointment':
            selected_time = request.form.get('time')
            # --- Mandatory Field Validation ---
            if not selected_time:
                flash("You must select a time for the appointment.", "error")
                return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            meeting_link = appointment.get('meeting_link') or _generate_meeting_link(appointment_id)

            # Validate Time: Cannot set past time
            appt_date_str = appointment.get('date')
            if appt_date_str:
                appt_date = datetime.datetime.strptime(appt_date_str, "%Y-%m-%d").date()
                now = datetime.datetime.now()
                if appt_date < now.date() or \
                   (appt_date == now.date() and datetime.datetime.strptime(selected_time, "%H:%M").time() <= now.time()):
                    flash("Cannot schedule a time that has already passed.", "error")
                    return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            # Check for time slot clash with other patients
            is_taken = appointments_collection.find_one({
                'doctor_name': session['doctor_name'], 'date': appointment.get('date'),
                'time': selected_time, '_id': {'$ne': ObjectId(appointment_id)},
                'status': {'$nin': ['Declined', 'Cancelled']}
            })
            if is_taken:
                flash(f"Time slot {selected_time} is already booked for another patient.", "error")
                return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            # All validations passed, prepare and execute update
            update_fields = {
                'time': selected_time,
                'status': 'Awaiting Payment',
                'meeting_link': meeting_link,
                'consultation_type': 'Online'
            }
            
            appointments_collection.update_one({'_id': ObjectId(appointment_id)}, {'$set': update_fields})
            
            # Send appointment scheduled email with payment details
            try:
                appointment_details = {
                    'doctor_name': session['doctor_name'],
                    'date': appointment.get('date'),
                    'time': selected_time,
                    'consultation_type': 'Online',
                    'symptoms': appointment.get('symptoms', ''),
                    'fees': doctor.get('consultation_fee', 500) if doctor else 500,
                    'location': doctor.get('clinic_address', '') if doctor else '',
                    'meeting_link': meeting_link
                }
                
                email_subject = f"📅 Your Appointment Scheduled with Dr. {session['doctor_name']} - Ready for Payment"
                
                email_body = f"""
                <html>
                    <body style="font-family: Arial, sans-serif; color: #333;">
                        <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                            <h2 style="color: #2563eb; text-align: center;">📅 Your Appointment has been Scheduled!</h2>
                            
                            <p>Dear {user.get('username', 'Patient')},</p>
                            
                            <p>Excellent! Dr. {session['doctor_name']} has scheduled your appointment. You can now proceed with payment to finalize the booking and access the meeting link (if applicable).</p>
                            
                            <!-- APPOINTMENT DETAILS SECTION -->
                            <div style="background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%); padding: 20px; border-left: 4px solid #0284c7; margin: 20px 0; border-radius: 6px;">
                                <h3 style="color: #0284c7; margin-top: 0;">👨‍⚕️ Appointment Details</h3>
                                <table style="width: 100%; border-collapse: collapse;">
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Doctor Name:</strong></td>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">Dr. {session['doctor_name']}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Date:</strong></td>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment.get('date')}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Time:</strong></td>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>{selected_time}</strong></td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Consultation Type:</strong></td>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment_details['consultation_type']}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>Symptoms:</strong></td>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment.get('symptoms', 'General Checkup')}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0;"><strong>Status:</strong></td>
                                        <td style="padding: 10px 0;"><span style="background: #fef08a; color: #b45309; padding: 4px 8px; border-radius: 4px; font-weight: bold;">AWAITING PAYMENT ⏳</span></td>
                                    </tr>
                                </table>
                            </div>
                            
                            <!-- PAYMENT SECTION -->
                            <div style="background: linear-gradient(135deg, #dcfce7 0%, #f0fdf4 100%); padding: 20px; border-left: 4px solid #16a34a; margin: 20px 0; border-radius: 6px;">
                                <h3 style="color: #16a34a; margin-top: 0;">💳 Complete Your Payment</h3>
                                <p style="color: #15803d; margin: 10px 0;">To finalize your appointment booking and access meeting details, please complete the payment below.</p>
                                <table style="width: 100%; border-collapse: collapse;">
                                    <tr>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #86efac;"><strong>Consultation Fees:</strong></td>
                                        <td style="padding: 10px 0; border-bottom: 1px solid #86efac; text-align: right;">₹{appointment_details['fees']}</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 10px 0;"><strong>Tax (10%):</strong></td>
                                        <td style="padding: 10px 0; text-align: right;">₹{appointment_details['fees'] * 0.10:.2f}</td>
                                    </tr>
                                    <tr style="background: #86efac;">
                                        <td style="padding: 12px; font-weight: bold; color: #065f46;">Total to Pay:</td>
                                        <td style="padding: 12px; text-align: right; font-weight: bold; color: #065f46; font-size: 18px;">₹{appointment_details['fees'] + (appointment_details['fees'] * 0.10):.2f}</td>
                                    </tr>
                                </table>
                            </div>
                            
                            <!-- CALL TO ACTION -->
                            <div style="text-align: center; margin: 25px 0;">
                                <a href="{request.url_root.rstrip('/')}/checkout/appointment?appointment_id={str(appointment_id)}" style="display: inline-block; background: linear-gradient(135deg, #16a34a 0%, #15803d 100%); color: white; padding: 15px 40px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; box-shadow: 0 4px 12px rgba(22, 163, 74, 0.4);">💳 Pay Now & Confirm Appointment</a>
                            </div>
                            
                            <!-- IMPORTANT NOTES -->
                            <div style="background-color: #fef3c7; padding: 12px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #f59e0b;">
                                <p style="margin: 0; color: #92400e;"><strong>📌 Important:</strong> After payment, you will receive your meeting link (for online consultations) and confirmation details via email.</p>
                            </div>
                            
                            <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                            
                            <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
                                Best Regards,<br>
                                <strong>Smart Health Management System</strong><br>
                                <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a>
                            </p>
                        </div>
                    </body>
                </html>
                """
                
                email_service.send_email(
                    user.get('email'),
                    email_subject,
                    email_body,
                    is_html=True
                )
                print(f"✅ Appointment scheduled email sent to {user.get('email')}")
            except Exception as e:
                print(f'⚠️ Error sending appointment scheduled email: {e}')
            
            # Create an in-app notification instead of emailing pre-payment
            try:
                notif = {
                    'user_id': appointment['user_id'],
                    'title': 'Appointment Scheduled',
                    'message': f"Dr. {session['doctor_name']} scheduled your appointment on {appointment.get('date')} at {selected_time}. Please complete payment to confirm and view the meeting link.",
                    'time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    'created_at': datetime.datetime.now()
                }
                try:
                    # set expiry at appointment time
                    if appointment.get('date') and selected_time:
                        appt_dt = datetime.datetime.strptime(f"{appointment.get('date')} {selected_time}", "%Y-%m-%d %H:%M")
                        notif['expires_at'] = appt_dt
                except Exception:
                    pass
                notifications_collection.insert_one(notif)
            except Exception as e:
                print(f"Could not create schedule notification: {e}")

            flash("Schedule updated and appointment confirmation sent to user!", "success")
        
        elif action == 'mark_completed':
            appointments_collection.update_one({'_id': ObjectId(appointment_id)}, {'$set': {'status': 'Completed'}})
            flash("Consultation completed. Medical records and prescriptions are now accessible.", "success")
            return redirect(url_for('manage_appointment', appointment_id=appointment_id))
                
        elif action == 'prescribe_medicine':
            if appointment.get('status') != 'Completed':
                flash("Please complete the consultation first.", "error")
                return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            medicine_name = request.form.get('medicine_name', '').strip()
            allowed_medicines = {medicine['name'] for medicine in MEDICINE_OPTIONS}
            if medicine_name not in allowed_medicines:
                flash("Please select a medicine from the approved dataset.", "error")
                return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            try:
                duration = int(request.form.get('duration', '0'))
            except ValueError:
                duration = 0
            if duration <= 0:
                flash("Medicine duration must be a positive number of days.", "error")
                return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            presc_id = ObjectId()
            prescription_data = {
                '_id': presc_id,
                'appointment_id': appointment_id,
                'user_id': user_id,
                'doctor_id': session['doctor_id'],
                'doctor_name': session['doctor_name'],
                'medicine_name': medicine_name,
                'frequency': request.form.get('frequency'),
                'duration': duration,
                'instructions': request.form.get('instructions'),
                'date': datetime.datetime.now().strftime("%Y-%m-%d")
            }
            
            # 1. Save to global prescriptions collection
            prescriptions_collection.insert_one(prescription_data)
            
            # 2. Embed in appointment document for easy retrieval in Inbox
            appointments_collection.update_one(
                {'_id': ObjectId(appointment_id)},
                {'$push': {'prescriptions': prescription_data}}
            )
            
            flash("Medicine prescribed.", "success")
            
        elif action == 'assign_meal':
            if appointment.get('status') != 'Completed':
                flash("Please complete the consultation first.", "error")
                return redirect(url_for('manage_appointment', appointment_id=appointment_id))

            meal_plan = request.form.get('meal_plan')
            meal_data = {
                'user_id': user_id,
                'doctor_id': session['doctor_id'],
                'meal_plan': meal_plan,
                'created_at': datetime.datetime.now(),
                'doctor_name': session['doctor_name']
            }
            
            # 1. Save to global meals collection
            meals_collection.insert_one(meal_data)
            
            # 2. Update appointment document for Inbox view
            appointments_collection.update_one(
                {'_id': ObjectId(appointment_id)},
                {'$set': {'meal_plan': meal_plan}}
            )
            
            flash("Meal plan assigned.", "success")
            
        return redirect(url_for('manage_appointment', appointment_id=appointment_id))

    # Fetch Data
    reports = list(reports_collection.find({'user_id': user_id}))
    prescriptions = list(prescriptions_collection.find({'appointment_id': appointment_id}))
    meals = list(meals_collection.find({'user_id': user_id}))
    medicines = []

    # --- Time Slot Logic ---
    # Generate slots: 9:15, 9:45, 10:15 ... until 17:15 (5:15 PM)
    time_slots = []
    start_time = datetime.datetime.strptime("09:15", "%H:%M")
    end_time = datetime.datetime.strptime("17:15", "%H:%M")
    
    # Check date to filter past slots
    appt_date_obj = None
    if appointment.get('date'):
        appt_date_obj = datetime.datetime.strptime(appointment['date'], "%Y-%m-%d").date()
    
    now = datetime.datetime.now()
    
    while start_time <= end_time:
        # Only add slot if it's in the future (or if date is future)
        if not appt_date_obj or appt_date_obj > now.date() or (appt_date_obj == now.date() and start_time.time() > now.time()):
            time_slots.append(start_time.strftime("%H:%M"))
            
        start_time += datetime.timedelta(minutes=30)
        
    # Identify taken slots for this doctor on this date
    taken_slots = []
    if appointment.get('date'):
        # Find other appointments for this doctor on the same date that have a time assigned
        others = appointments_collection.find({
            'doctor_name': session['doctor_name'],
            'date': appointment['date'],
            '_id': {'$ne': ObjectId(appointment_id)}, # Exclude current appointment
            'time': {'$ne': None},
            'status': {'$nin': ['Declined', 'Cancelled']}
        })
        taken_slots = [appt['time'] for appt in others if appt.get('time')]
    
    return render_template('doctor_manage_appointment.html', 
                           appointment=appointment, 
                           user=user, 
                           reports=reports, 
                           prescriptions=prescriptions, 
                           meals=meals, 
                           medicines=medicines,
                           doctor=doctor,
                           time_slots=time_slots,
                           taken_slots=taken_slots)

    # --- Delete Routes for Doctor ---
@app.route('/doctor/delete_prescription/<prescription_id>', methods=['POST'])
@doctor_required
def delete_prescription(prescription_id):
    # Get appointment_id before deleting to redirect back
    presc = prescriptions_collection.find_one({'_id': ObjectId(prescription_id)})
    appt_id = presc.get('appointment_id') if presc else request.form.get('appointment_id')
    
    # Delete from collection
    prescriptions_collection.delete_one({'_id': ObjectId(prescription_id)})
    
    # Delete from embedded list in appointment if it exists
    if appt_id:
        appointments_collection.update_one(
            {'_id': ObjectId(appt_id)},
            {'$pull': {'prescriptions': {'_id': ObjectId(prescription_id)}}}
        )
        return redirect(url_for('manage_appointment', appointment_id=appt_id))
        
    return redirect(url_for('doctor_dashboard'))

@app.route('/doctor/delete_meal/<meal_id>', methods=['POST'])
@doctor_required
def delete_meal(meal_id):
    appointment_id = request.form.get('appointment_id')
    meals_collection.delete_one({'_id': ObjectId(meal_id)})
    if appointment_id:
        return redirect(url_for('manage_appointment', appointment_id=appointment_id))
    return redirect(url_for('doctor_dashboard'))

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == '__main__':
    # Ensure templates folder exists to avoid errors
    if not os.path.exists('templates'):
        os.makedirs('templates')
        
    app.run(debug=True,port=5001)   