import stripe
import os
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import io

# Initialize Stripe with test key
stripe.api_key = os.getenv('STRIPE_SECRET_KEY', 'sk_test_your_test_key_here')

class PaymentHandler:
    """Handle Stripe payments and invoice generation."""
    
    @staticmethod
    def create_payment_intent(amount, currency='usd', metadata=None):
        """
        Create a Stripe payment intent.
        
        Args:
            amount: Amount in rupees (e.g., 5000 for ₹5000)
            currency: Currency code (default: 'usd')
            metadata: Additional metadata to attach to the intent
            
        Returns:
            Payment intent object
        """
        try:
            intent = stripe.PaymentIntent.create(
                amount=amount,
                currency=currency,
                metadata=metadata or {},
                description="Health Management System Payment"
            )
            return intent
        except stripe.error.StripeError as e:
            return {'error': str(e)}
    
    @staticmethod
    def confirm_payment(payment_intent_id):
        """Verify if a payment intent was successful."""
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            return intent.status == 'succeeded'
        except stripe.error.StripeError as e:
            return False
    
    @staticmethod
    def generate_invoice(order_data):
        """
        Generate a beautiful professional PDF invoice with premium design.
        """
        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        elements = []
        styles = getSampleStyleSheet()
        
        # ===== HEADER WITH BRAND =====
        header_table_data = [
            [
                Paragraph("<b>🏥 SMART HEALTH</b>", ParagraphStyle(
                    'LogoStyle',
                    parent=styles['Normal'],
                    fontSize=20,
                    textColor=colors.HexColor('#005D7E'),
                    fontName='Helvetica-Bold'
                )),
                Paragraph("<b>INVOICE</b>", ParagraphStyle(
                    'InvoiceTitle',
                    parent=styles['Normal'],
                    fontSize=18,
                    textColor=colors.HexColor('#169C81'),
                    fontName='Helvetica-Bold',
                    alignment=TA_RIGHT
                ))
            ]
        ]
        header_table = Table(header_table_data, colWidths=[3*inch, 3.5*inch])
        header_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.15*inch))
        
        # Decorative line
        line = HRFlowable(
            width="100%",
            thickness=2,
            lineCap='round',
            color=colors.HexColor('#169C81')
        )
        elements.append(line)
        elements.append(Spacer(1, 0.2*inch))
        
        # ===== INVOICE INFO SECTION =====
        header_style = ParagraphStyle(
            'HeaderStyle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=colors.HexColor('#005D7E'),
            fontName='Helvetica-Bold',
            spaceAfter=4
        )
        
        label_style = ParagraphStyle(
            'LabelStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            spaceAfter=2
        )
        
        info_data = [
            [
                Paragraph("<b>Invoice Details</b>", header_style),
                '',
                Paragraph("<b>Bill To</b>", header_style)
            ],
            [
                Paragraph(f"<b>Invoice #:</b> {order_data.get('invoice_id', 'N/A')}", label_style),
                '',
                Paragraph(f"<b>Name:</b> {order_data.get('user_name', 'N/A')}", label_style)
            ],
            [
                Paragraph(f"<b>Date:</b> {order_data.get('date', '')}", label_style),
                '',
                Paragraph(f"<b>Email:</b> {order_data.get('user_email', 'N/A')}", label_style)
            ]
        ]
        
        if order_data.get('doctor_name'):
            info_data.append([
                Paragraph(f"<b>Doctor:</b> Dr. {order_data.get('doctor_name', 'N/A')}", label_style),
                '',
                ''
            ])
        
        # Add appointment details to invoice
        if order_data.get('appointment_date'):
            info_data.append([
                Paragraph(f"<b>Appointment Date:</b> {order_data.get('appointment_date', 'N/A')}", label_style),
                '',
                ''
            ])
        
        if order_data.get('appointment_time'):
            info_data.append([
                Paragraph(f"<b>Appointment Time:</b> {order_data.get('appointment_time', 'N/A')}", label_style),
                '',
                ''
            ])
        
        if order_data.get('symptoms'):
            info_data.append([
                Paragraph(f"<b>Reason/Symptoms:</b> {order_data.get('symptoms', 'N/A')}", label_style),
                '',
                ''
            ])
        
        if order_data.get('clinic_address'):
            info_data.append([
                Paragraph(f"<b>Location:</b> {order_data.get('clinic_address', 'N/A')}", label_style),
                '',
                ''
            ])
        
        if order_data.get('payment_status'):
            info_data.append([
                Paragraph(f"<b>Payment Status:</b> <font color='#169C81'>{order_data.get('payment_status', 'N/A')}</font>", label_style),
                '',
                ''
            ])
        
        info_table = Table(info_data, colWidths=[2.2*inch, 0.8*inch, 3*inch])
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#E4F9D1')),
            ('BACKGROUND', (2, 0), (2, 0), colors.HexColor('#F1F9FD')),
        ]))
        elements.append(info_table)
        elements.append(Spacer(1, 0.25*inch))
        
        # ===== ITEMS TABLE =====
        items = order_data.get('items', [])
        items_data = [
            [
                Paragraph('<b>Description</b>', ParagraphStyle(
                    'TableHeader',
                    parent=styles['Normal'],
                    fontSize=11,
                    textColor=colors.whitesmoke,
                    fontName='Helvetica-Bold'
                )),
                Paragraph('<b>Qty</b>', ParagraphStyle(
                    'TableHeader',
                    parent=styles['Normal'],
                    fontSize=11,
                    textColor=colors.whitesmoke,
                    fontName='Helvetica-Bold',
                    alignment=TA_CENTER
                )),
                Paragraph('<b>Unit Price</b>', ParagraphStyle(
                    'TableHeader',
                    parent=styles['Normal'],
                    fontSize=11,
                    textColor=colors.whitesmoke,
                    fontName='Helvetica-Bold',
                    alignment=TA_RIGHT
                )),
                Paragraph('<b>Amount</b>', ParagraphStyle(
                    'TableHeader',
                    parent=styles['Normal'],
                    fontSize=11,
                    textColor=colors.whitesmoke,
                    fontName='Helvetica-Bold',
                    alignment=TA_RIGHT
                ))
            ]
        ]
        
        for idx, item in enumerate(items):
            items_data.append([
                Paragraph(item.get('description', ''), ParagraphStyle(
                    'ItemDesc',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333')
                )),
                Paragraph(str(item.get('quantity', 1)), ParagraphStyle(
                    'ItemQty',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333'),
                    alignment=TA_CENTER
                )),
                Paragraph(f"₹{item.get('price', 0):.2f}", ParagraphStyle(
                    'ItemPrice',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333'),
                    alignment=TA_RIGHT
                )),
                Paragraph(f"₹{float(item.get('quantity', 1)) * float(item.get('price', 0)):.2f}", ParagraphStyle(
                    'ItemAmount',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#169C81'),
                    fontName='Helvetica-Bold',
                    alignment=TA_RIGHT
                ))
            ])
        
        items_table = Table(
            items_data,
            colWidths=[3.2*inch, 1*inch, 1.3*inch, 1.5*inch]
        )
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#005D7E')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F9F9')]),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 1), (1, -1), 'CENTER'),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ]))
        elements.append(items_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # ===== SUMMARY SECTION =====
        summary_data = [
            [
                Paragraph('', styles['Normal']),
                Paragraph('<b>Subtotal</b>', ParagraphStyle(
                    'SummaryLabel',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333'),
                    alignment=TA_RIGHT
                )),
                Paragraph(f"₹{order_data.get('subtotal', 0):.2f}", ParagraphStyle(
                    'SummaryValue',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333'),
                    alignment=TA_RIGHT,
                    fontName='Helvetica-Bold'
                ))
            ],
            [
                Paragraph('', styles['Normal']),
                Paragraph('<b>Tax (10%)</b>', ParagraphStyle(
                    'SummaryLabel',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333'),
                    alignment=TA_RIGHT
                )),
                Paragraph(f"₹{order_data.get('tax', 0):.2f}", ParagraphStyle(
                    'SummaryValue',
                    parent=styles['Normal'],
                    fontSize=10,
                    textColor=colors.HexColor('#333333'),
                    alignment=TA_RIGHT,
                    fontName='Helvetica-Bold'
                ))
            ],
            [
                Paragraph('', styles['Normal']),
                Paragraph('<b>TOTAL AMOUNT</b>', ParagraphStyle(
                    'TotalLabel',
                    parent=styles['Normal'],
                    fontSize=12,
                    textColor=colors.whitesmoke,
                    alignment=TA_RIGHT,
                    fontName='Helvetica-Bold'
                )),
                Paragraph(f"₹{order_data.get('total', 0):.2f}", ParagraphStyle(
                    'TotalValue',
                    parent=styles['Normal'],
                    fontSize=13,
                    textColor=colors.whitesmoke,
                    alignment=TA_RIGHT,
                    fontName='Helvetica-Bold'
                ))
            ]
        ]
        
        summary_table = Table(
            summary_data,
            colWidths=[3.2*inch, 1.8*inch, 1.8*inch]
        )
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, 1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 1), 6),
            ('TOPPADDING', (0, 2), (-1, 2), 10),
            ('BOTTOMPADDING', (0, 2), (-1, 2), 10),
            ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#169C81')),
            ('GRID', (1, 0), (-1, 1), 1, colors.HexColor('#EEEEEE')),
            ('GRID', (1, 2), (-1, 2), 0, colors.whitesmoke),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 0.4*inch))
        
        # ===== FOOTER =====
        footer_line = HRFlowable(
            width="100%",
            thickness=1,
            lineCap='round',
            color=colors.HexColor('#169C81')
        )
        elements.append(footer_line)
        elements.append(Spacer(1, 0.1*inch))
        
        footer_data = [
            [
                Paragraph('✓ Payment Received', ParagraphStyle(
                    'FooterText',
                    parent=styles['Normal'],
                    fontSize=9,
                    textColor=colors.HexColor('#27ae60'),
                    fontName='Helvetica-Bold'
                )),
                Paragraph('Thank you for your trust in Smart Health', ParagraphStyle(
                    'FooterCenter',
                    parent=styles['Normal'],
                    fontSize=9,
                    textColor=colors.HexColor('#666666'),
                    alignment=TA_CENTER
                )),
                Paragraph('Contact: support@smarthealth.com', ParagraphStyle(
                    'FooterText',
                    parent=styles['Normal'],
                    fontSize=9,
                    textColor=colors.HexColor('#666666'),
                    alignment=TA_RIGHT
                ))
            ]
        ]
        
        footer_table = Table(footer_data, colWidths=[2*inch, 3.5*inch, 2*inch])
        footer_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('ALIGN', (1, 0), (1, 0), 'CENTER'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(footer_table)
        
        # Build PDF
        doc.build(elements)
        pdf_buffer.seek(0)
        
        return pdf_buffer
