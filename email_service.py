import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import os
from datetime import datetime

class EmailService:
    """Email service for sending confirmations and notifications."""
    
    def __init__(self, smtp_server='smtp.gmail.com', smtp_port=587, 
                 sender_email=None, sender_password=None):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email or os.getenv('MAIL_USERNAME', 'your_email@gmail.com')
        self.sender_password = sender_password or os.getenv('MAIL_PASSWORD', 'your_app_password')
    
    def send_email(self, to_email, subject, body, is_html=False, attachments=None):
        """
        Send email with optional attachments.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body: Email body content
            is_html: Whether body is HTML (default: False for plain text)
            attachments: List of file paths to attach
            
        Returns:
            True if successful, False otherwise
        """
        if not to_email:
            print("Email not sent: recipient address is empty")
            return False
        if not self.sender_email or self.sender_email == 'your_email@gmail.com':
            print("Email not sent: configure MAIL_USERNAME in .env")
            return False
        if not self.sender_password or self.sender_password == 'your_app_password':
            print("Email not sent: configure a Gmail App Password in MAIL_PASSWORD")
            return False

        server = None
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = self.sender_email
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # Add body
            mime_type = 'html' if is_html else 'plain'
            msg.attach(MIMEText(body, mime_type))
            
            # Add attachments if provided
            if attachments:
                for file_path in attachments:
                    self._attach_file(msg, file_path)
            
            # Connect and send
            print(f"Connecting to {self.smtp_server}:{self.smtp_port}...")
            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
            server.starttls()
            print(f"Logging in as {self.sender_email}...")
            server.login(self.sender_email, self.sender_password)
            print(f"Sending email to {to_email}...")
            server.send_message(msg)
            server.quit()
            
            print(f"Email sent successfully to {to_email}")
            return True
        except Exception as e:
            print(f"Error sending email to {to_email}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass
    
    def _attach_file(self, msg, file_path):
        """Attach a file to the email message."""
        try:
            with open(file_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {os.path.basename(file_path)}'
            )
            msg.attach(part)
        except Exception as e:
            print(f"Error attaching file {file_path}: {str(e)}")
    
    def send_appointment_confirmation(self, user_email, user_name, appointment_data):
        """Send appointment booking confirmation email."""
        subject = "Appointment Confirmation - Smart Health"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #2563eb; text-align: center;">Appointment Confirmed ✓</h2>
                    
                    <p>Dear {user_name},</p>
                    
                    <p>Your appointment has been successfully booked. Here are the details:</p>
                    
                    <div style="background-color: #f0f9ff; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0;">
                        <p><strong>👨‍⚕️ Doctor:</strong> {appointment_data.get('doctor_name', 'N/A')}</p>
                        <p><strong>📅 Date:</strong> {appointment_data.get('date', 'N/A')}</p>
                        <p><strong>⏰ Time:</strong> {appointment_data.get('time', 'To be confirmed by doctor')}</p>
                        <p><strong>🩺 Reason/Illness:</strong> {appointment_data.get('symptoms', 'Not specified')}</p>
                        <p><strong>💰 Consultation Fees:</strong> ₹{appointment_data.get('fees', 'N/A')}</p>
                        <p><strong>📍 Location:</strong> {appointment_data.get('clinic_address', 'Online Consultation')}</p>
                        <p><strong>💻 Consultation Type:</strong> {appointment_data.get('consultation_type', 'Online')}</p>
                        <p><strong>✅ Status:</strong> <span style="color: #16a34a; font-weight: bold;">CONFIRMED & PAID</span></p>
                    </div>
                    
                    <div style="background-color: #fff3cd; padding: 12px; border-radius: 6px; margin: 15px 0;">
                        <p style="margin: 0; color: #856404;"><strong>📋 Appointment Summary:</strong> You have successfully booked an appointment with <strong>{appointment_data.get('doctor_name', 'your doctor')}</strong> on <strong>{appointment_data.get('date', 'N/A')}</strong> at <strong>{appointment_data.get('time', 'TBD')}</strong> for <strong>{appointment_data.get('symptoms', 'consultation')}</strong>.</p>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p>You can manage your appointment from your dashboard. The doctor may contact you before the appointment date if needed.</p>
                    
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        Best Regards,<br>
                        <strong>Smart Health Management System</strong><br>
                        <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a>
                    </p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body, is_html=True)
    
    def send_lab_test_confirmation(self, user_email, user_name, lab_data):
        """Send lab test booking confirmation email."""
        subject = "Lab Test Booking Confirmation - Smart Health"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #2563eb; text-align: center;">Lab Test Booked ✓</h2>
                    
                    <p>Dear {user_name},</p>
                    
                    <p>Your lab test has been successfully booked. Here are the details:</p>
                    
                    <div style="background-color: #f0f9ff; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0;">
                        <p><strong>Test Name:</strong> {lab_data.get('test_name', 'N/A')}</p>
                        <p><strong>Booking Date:</strong> {lab_data.get('date', 'N/A')}</p>
                        <p><strong>Test Cost:</strong> ₹{lab_data.get('cost', 'N/A')}</p>
                        <p><strong>Status:</strong> <span style="color: #16a34a; font-weight: bold;">CONFIRMED</span></p>
                    </div>
                    
                    <p><strong>Instructions:</strong></p>
                    <ul>
                        <li>Please bring a valid ID and insurance card if applicable</li>
                        <li>Follow any pre-test instructions provided</li>
                        <li>Arrive 10 minutes early</li>
                        <li>Results will be available within 24-48 hours</li>
                    </ul>
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p>You can view your bookings and results from your dashboard.</p>
                    
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        Best Regards,<br>
                        <strong>Smart Health Management System</strong><br>
                        <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a>
                    </p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body, is_html=True)
    
    def send_payment_confirmation(self, user_email, user_name, payment_data, invoice_file_path=None, invoice_url=None):
        """Send payment confirmation email with optional invoice attachment."""
        subject = "Payment Confirmation - Smart Health"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #2563eb; text-align: center;">Payment Successful ✓</h2>
                    
                    <p>Dear {user_name},</p>
                    
                    <p>Thank you for your payment. Your transaction has been processed successfully.</p>
                    
                    <div style="background-color: #f0f9ff; padding: 15px; border-left: 4px solid #2563eb; margin: 20px 0;">
                        <p><strong>💳 Transaction ID:</strong> {payment_data.get('transaction_id', 'N/A')}</p>
                        <p><strong>💰 Amount Paid:</strong> ₹{payment_data.get('amount', 'N/A')}</p>
                        <p><strong>📅 Payment Date:</strong> {payment_data.get('date', 'N/A')}</p>
                        <p><strong>💳 Payment Method:</strong> {payment_data.get('method', 'Card')}</p>
                        <p><strong>✅ Status:</strong> <span style="color: #16a34a; font-weight: bold;">COMPLETED</span></p>
                    </div>
                    
                    <p><strong>🏥 Service Details:</strong> {payment_data.get('description', 'Service')}</p>
                    
                    <div style="background-color: #d1f2eb; padding: 12px; border-radius: 6px; margin: 15px 0;">
                        <p style="margin: 0; color: #0c5460;"><strong>📄 Invoice Details:</strong> Your payment invoice is attached to this email. It includes complete appointment details including doctor name, appointment date & time, symptoms/reason for visit, and payment breakdown.</p>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p>Please find the attached invoice for your records. Your appointment or test is now confirmed.</p>
                    {f'<p style="text-align: center; margin: 20px 0;"><a href="{invoice_url}" style="display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 12px 30px; border-radius: 8px; text-decoration: none; font-weight: bold; box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);">🔗 View Invoice Online</a></p>' if invoice_url else ''}
                    
                    <p style="color: #666; font-size: 12px; margin-top: 20px;">
                        Best Regards,<br>
                        <strong>Smart Health Management System</strong><br>
                        <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a>
                    </p>
                </div>
            </body>
        </html>
        """
        
        attachments = [invoice_file_path] if invoice_file_path and os.path.exists(invoice_file_path) else None
        return self.send_email(user_email, subject, body, is_html=True, attachments=attachments)
    
    def send_combined_appointment_payment_email(self, user_email, user_name, appointment_data, payment_data, invoice_file_path=None, invoice_url=None):
        """Send combined appointment confirmation + payment invoice in one email."""
        subject = "Appointment Confirmed & Payment Received - Smart Health"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 700px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #16a34a; text-align: center;">✅ Appointment Confirmed & Payment Received</h2>
                    
                    <p>Dear {user_name},</p>
                    
                    <p>Your appointment has been successfully confirmed and your payment has been processed. Here are the complete details:</p>
                    
                    <!-- APPOINTMENT DETAILS SECTION -->
                    <div style="background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%); padding: 20px; border-left: 4px solid #0284c7; margin: 20px 0; border-radius: 6px;">
                        <h3 style="color: #0284c7; margin-top: 0;">📋 Appointment Details</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>👨‍⚕️ Doctor:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment_data.get('doctor_name', 'N/A')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>📅 Appointment Date:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><span style="background: #dbeafe; padding: 4px 8px; border-radius: 4px;">{appointment_data.get('date', 'N/A')}</span></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>⏰ Appointment Time:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><span style="background: #dbeafe; padding: 4px 8px; border-radius: 4px;">{appointment_data.get('time', 'To be confirmed')}</span></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>🩺 Reason/Illness:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment_data.get('symptoms', 'General Consultation')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>📍 Clinic Location:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment_data.get('clinic_address', 'Online Consultation')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>💻 Consultation Type:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{appointment_data.get('consultation_type', 'Online')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>📹 Meeting Link:</strong></td>
                                <td style="padding: 10px 0;"><a href="{appointment_data.get('meeting_link', '#')}" style="color: #2563eb; font-weight: bold;">Join Online Consultation</a></td>
                            </tr>
                        </table>
                    </div>
                    
                    <!-- PAYMENT INVOICE SECTION -->
                    <div style="background: linear-gradient(135deg, #f0fdf4 0%, #f7fee7 100%); padding: 20px; border-left: 4px solid #16a34a; margin: 20px 0; border-radius: 6px;">
                        <h3 style="color: #16a34a; margin-top: 0;">💳 Payment & Invoice Details</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7;"><strong>💰 Consultation Fees:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7; text-align: right;"><strong>₹{appointment_data.get('fees', 'N/A')}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7;"><strong>🧾 Tax (10%):</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7; text-align: right;">₹{payment_data.get('tax', 0):.2f}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7;"><strong>💵 Total Amount Paid:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7; text-align: right;"><strong style="color: #16a34a; font-size: 18px;">₹{payment_data.get('amount', 'N/A')}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>🧾 Invoice ID:</strong></td>
                                <td style="padding: 10px 0;">{payment_data.get('invoice_id', 'N/A')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>🕐 Transaction Date:</strong></td>
                                <td style="padding: 10px 0;">{payment_data.get('date', 'N/A')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>💳 Payment Method:</strong></td>
                                <td style="padding: 10px 0;">{payment_data.get('method', 'Card')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>✅ Payment Status:</strong></td>
                                <td style="padding: 10px 0;"><span style="background: #dcfce7; color: #16a34a; padding: 4px 8px; border-radius: 4px; font-weight: bold;">COMPLETED</span></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>🔐 Transaction ID:</strong></td>
                                <td style="padding: 10px 0; font-size: 12px;">{payment_data.get('transaction_id', 'N/A')}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <!-- IMPORTANT NOTES -->
                    <div style="background-color: #fffbeb; padding: 12px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #f59e0b;">
                        <p style="margin: 0; color: #92400e;"><strong>📌 Important:</strong> Please arrive 10-15 minutes before your scheduled appointment time. Bring a valid ID and any relevant medical documents if applicable.</p>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p><strong>What's Next?</strong></p>
                    <ul style="color: #666;">
                        <li>Save this email for your records</li>
                        <li>The doctor may contact you before the appointment if needed</li>
                        <li>Your invoice is attached to this email</li>
                        <li>You can reschedule if needed from your dashboard</li>
                    </ul>
                    
                    {f'<div style="text-align: center; margin: 25px 0;"><a href="{invoice_url}" style="display: inline-block; background: linear-gradient(135deg, #16a34a 0%, #15803d 100%); color: white; padding: 12px 30px; border-radius: 8px; text-decoration: none; font-weight: bold; box-shadow: 0 4px 12px rgba(22, 163, 74, 0.3);">📄 View Full Invoice Online</a></div>' if invoice_url else ''}
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
                        Best Regards,<br>
                        <strong>Smart Health Management System</strong><br>
                        <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a><br>
                        <span style="font-size: 10px; color: #999;">© 2024 Smart Health. All rights reserved.</span>
                    </p>
                </div>
            </body>
        </html>
        """
        
        attachments = [invoice_file_path] if invoice_file_path and os.path.exists(invoice_file_path) else None
        return self.send_email(user_email, subject, body, is_html=True, attachments=attachments)
    
    def send_combined_lab_payment_email(self, user_email, user_name, lab_data, payment_data, invoice_file_path=None, invoice_url=None):
        """Send combined lab test booking + payment invoice in one email."""
        subject = "Lab Test Booked & Payment Received - Smart Health"
        
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 700px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #16a34a; text-align: center;">✅ Lab Test Confirmed & Payment Received</h2>
                    
                    <p>Dear {user_name},</p>
                    
                    <p>Your lab test has been successfully booked and your payment has been processed. Here are the complete details:</p>
                    
                    <!-- LAB TEST DETAILS SECTION -->
                    <div style="background: linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%); padding: 20px; border-left: 4px solid #0284c7; margin: 20px 0; border-radius: 6px;">
                        <h3 style="color: #0284c7; margin-top: 0;">🔬 Lab Test Details</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>🧪 Test Name:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{lab_data.get('test_name', 'N/A')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>🏥 Hospital/Lab:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{lab_data.get('hospital_name', 'Standard Lab')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>📅 Booking Date:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{lab_data.get('booking_date', 'Today')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>🗓️ Scheduled Date/Time:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{(lab_data.get('scheduled_date') + ' • ' + lab_data.get('scheduled_time')) if lab_data.get('scheduled_date') and lab_data.get('scheduled_time') else 'To be confirmed'}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;"><strong>📍 Location:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #bfdbfe;">{lab_data.get('address', 'TBD - Hospital will confirm')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>✅ Status:</strong></td>
                                <td style="padding: 10px 0;"><span style="background: #dbeafe; color: #0284c7; padding: 4px 8px; border-radius: 4px; font-weight: bold;">CONFIRMED</span></td>
                            </tr>
                        </table>
                    </div>
                    
                    <!-- PAYMENT INVOICE SECTION -->
                    <div style="background: linear-gradient(135deg, #f0fdf4 0%, #f7fee7 100%); padding: 20px; border-left: 4px solid #16a34a; margin: 20px 0; border-radius: 6px;">
                        <h3 style="color: #16a34a; margin-top: 0;">💳 Payment & Invoice Details</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7;"><strong>💰 Test Cost:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7; text-align: right;"><strong>₹{lab_data.get('cost', 'N/A')}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7;"><strong>🧾 Tax (10%):</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7; text-align: right;">₹{payment_data.get('tax', 0):.2f}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7;"><strong>💵 Total Amount Paid:</strong></td>
                                <td style="padding: 10px 0; border-bottom: 1px solid #dcfce7; text-align: right;"><strong style="color: #16a34a; font-size: 18px;">₹{payment_data.get('amount', 'N/A')}</strong></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>🧾 Invoice ID:</strong></td>
                                <td style="padding: 10px 0;">{payment_data.get('invoice_id', 'N/A')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>🕐 Transaction Date:</strong></td>
                                <td style="padding: 10px 0;">{payment_data.get('date', 'N/A')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>💳 Payment Method:</strong></td>
                                <td style="padding: 10px 0;">{payment_data.get('method', 'Card')}</td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>✅ Payment Status:</strong></td>
                                <td style="padding: 10px 0;"><span style="background: #dcfce7; color: #16a34a; padding: 4px 8px; border-radius: 4px; font-weight: bold;">COMPLETED</span></td>
                            </tr>
                            <tr>
                                <td style="padding: 10px 0;"><strong>🔐 Transaction ID:</strong></td>
                                <td style="padding: 10px 0; font-size: 12px;">{payment_data.get('transaction_id', 'N/A')}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <!-- IMPORTANT NOTES -->
                    <div style="background-color: #fffbeb; padding: 12px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #f59e0b;">
                        <p style="margin: 0; color: #92400e;"><strong>📌 Important:</strong> Please bring a valid ID and insurance card if applicable. The hospital will contact you with the exact appointment date and time. Follow any pre-test instructions provided by the lab.</p>
                    </div>
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p><strong>What's Next?</strong></p>
                    <ul style="color: #666;">
                        <li>The hospital/lab will contact you to schedule the exact test date and time</li>
                        <li>Save this email and invoice for your records</li>
                        <li>Follow any pre-test instructions provided</li>
                        <li>Results will typically be available within 24-48 hours after the test</li>
                        <li>You can reschedule if needed from your dashboard</li>
                    </ul>
                    
                    {f'<div style="text-align: center; margin: 25px 0;"><a href="{invoice_url}" style="display: inline-block; background: linear-gradient(135deg, #16a34a 0%, #15803d 100%); color: white; padding: 12px 30px; border-radius: 8px; text-decoration: none; font-weight: bold; box-shadow: 0 4px 12px rgba(22, 163, 74, 0.3);">📄 View Full Invoice Online</a></div>' if invoice_url else ''}
                    
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    
                    <p style="color: #666; font-size: 12px; text-align: center; margin-top: 20px;">
                        Best Regards,<br>
                        <strong>Smart Health Management System</strong><br>
                        <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a><br>
                        <span style="font-size: 10px; color: #999;">© 2024 Smart Health. All rights reserved.</span>
                    </p>
                </div>
            </body>
        </html>
        """
        
        attachments = [invoice_file_path] if invoice_file_path and os.path.exists(invoice_file_path) else None
        return self.send_email(user_email, subject, body, is_html=True, attachments=attachments)

    def send_generic_notification(self, user_email, subject, message):
        """Send a generic notification email."""
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                    <h2 style="color: #2563eb;">{subject}</h2>
                    <p>{message}</p>
                    <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 20px 0;">
                    <p style="color: #666; font-size: 12px;">
                        <strong>Smart Health Management System</strong><br>
                        <a href="http://localhost:5000" style="color: #2563eb; text-decoration: none;">Visit Dashboard</a>
                    </p>
                </div>
            </body>
        </html>
        """
        
        return self.send_email(user_email, subject, body, is_html=True)
