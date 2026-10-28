# Payment Setup Guide

## Quick Stripe Setup

### 1. Get Your Stripe Keys
1. Go to [Stripe Dashboard](https://dashboard.stripe.com)
2. Click on your profile → API keys
3. Copy your **Secret Key** (`sk_test_...` or `sk_live_...`)
4. Copy your **Publishable Key** (`pk_test_...` or `pk_live_...`)

### 2. Configure Environment Variables
Create a `.env` file in the project root with your Stripe keys:

```env
STRIPE_SECRET_KEY=sk_test_YOUR_KEY_HERE
STRIPE_PUBLISHABLE_KEY=pk_test_YOUR_KEY_HERE
```

### 3. Email Setup (for payment notifications)
```env
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_16_character_app_password
```

**For Gmail Users:**
- Enable 2-Step Verification on your account
- Generate an [App Password](https://myaccount.google.com/apppasswords) 
- Use the 16-character password in `MAIL_PASSWORD`

## Testing Payments

### 1. Use Test Cards
Stripe provides test card numbers for development:

- **Success**: 4242 4242 4242 4242
- **Decline**: 4000 0000 0000 0002
- **3D Secure**: 4000 0025 0000 3155

### 2. Test Payment Flow
1. Book an appointment or lab test
2. Click "Pay" button
3. Use test card numbers above
4. Any future date for expiry (e.g., 12/25)
5. Any 3-digit CVC (e.g., 123)

## Common Issues & Solutions

### Issue: "Stripe is not configured"
**Solution**: 
- Check `.env` file exists in project root
- Verify `STRIPE_SECRET_KEY` is set correctly
- Restart the Flask server

### Issue: "Payment intent error"
**Solution**:
- Check cardholder name is filled
- Ensure valid card number
- Verify amount is positive (> $1)
- Check browser console for JavaScript errors

### Issue: Email notifications not sending
**Solution**:
- Verify Gmail App Password (not regular password)
- Enable "Less secure app access" if not using App Password
- Check MAIL_USERNAME matches your email

## API Response Format

The payment API returns JSON responses:

```json
{
  "success": true,
  "client_secret": "pi_1234567890_secret_abcdefghij"
}
```

On error:
```json
{
  "success": false,
  "message": "Specific error message describing the issue"
}
```

## Security Notes

⚠️ **Important Security Guidelines:**

1. **Never commit `.env` file** - It contains sensitive keys
2. **Use live keys only in production** - Never use test keys in production
3. **Enable HTTPS** - Always use SSL/TLS for payments
4. **Validate amounts server-side** - Never trust client-side amounts
5. **Store payment intents** - Keep track of all payment attempts
6. **Handle errors gracefully** - Show user-friendly error messages

## Next Steps

1. Update your `.env` file with real Stripe keys
2. Test the payment flow with test cards
3. Verify email notifications are working
4. Switch to live keys when ready for production
5. Enable webhook handlers for production use
