"""
Camélia — Stripe Integration
Add these routes to your app.py or import as a Blueprint.
"""
import os
import stripe
from flask import Blueprint, request, jsonify, session, redirect
from db import get_db, q1, ex, PH

stripe_bp = Blueprint('stripe', __name__)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
APP_URL = os.environ.get('APP_URL', 'https://camelia-02uo.onrender.com')

# Price IDs from Stripe Dashboard
STRIPE_PRICES = {
    'starter': os.environ.get('STRIPE_STARTER_PRICE_ID', ''),
    'pro':     os.environ.get('STRIPE_PRO_PRICE_ID', ''),
}

PLAN_CONFIG = {
    'starter':    {'max_employees': 10,  'max_admins': 1},
    'pro':        {'max_employees': 100, 'max_admins': 5},
    'enterprise': {'max_employees': 9999,'max_admins': 999},
}

# ═══════════════════════════════════════════
# CHECKOUT — Start a subscription
# ═══════════════════════════════════════════
@stripe_bp.route('/api/stripe/checkout', methods=['POST'])
def create_checkout():
    if 'employee_id' not in session:
        return jsonify({"error": "Non authentifié"}), 401
    if session.get('role') != 'admin':
        return jsonify({"error": "Seul un admin peut gérer l'abonnement"}), 403

    data = request.json or {}
    plan = data.get('plan', 'starter')

    if plan not in STRIPE_PRICES or not STRIPE_PRICES[plan]:
        return jsonify({"error": "Plan invalide"}), 400

    company_id = session['company_id']

    with get_db() as conn:
        company = q1(f"SELECT * FROM companies WHERE id={PH}", (company_id,), conn)
        employee = q1(f"SELECT * FROM employees WHERE id={PH}", (session['employee_id'],), conn)

    if not company or not employee:
        return jsonify({"error": "Entreprise introuvable"}), 404

    try:
        # Get or create Stripe customer
        stripe_customer_id = company.get('stripe_customer_id')
        if not stripe_customer_id:
            customer = stripe.Customer.create(
                email=employee['email'],
                name=company['name'],
                metadata={'company_id': company_id, 'company_name': company['name']}
            )
            stripe_customer_id = customer.id
            with get_db() as conn:
                ex(f"UPDATE companies SET stripe_customer_id={PH} WHERE id={PH}",
                   (stripe_customer_id, company_id), conn)

        # If already subscribed, redirect to billing portal instead
        stripe_sub_id = company.get('stripe_subscription_id')
        if stripe_sub_id:
            try:
                sub = stripe.Subscription.retrieve(stripe_sub_id)
                if sub.status in ('active', 'trialing'):
                    # Use billing portal to change plan
                    portal = stripe.billing_portal.Session.create(
                        customer=stripe_customer_id,
                        return_url=f"{APP_URL}/app"
                    )
                    return jsonify({"url": portal.url})
            except stripe.error.InvalidRequestError:
                pass  # Sub not found, create new checkout

        # Create checkout session
        checkout = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=['card'],
            mode='subscription',
            line_items=[{'price': STRIPE_PRICES[plan], 'quantity': 1}],
            success_url=f"{APP_URL}/app?payment=success",
            cancel_url=f"{APP_URL}/app?payment=cancelled",
            metadata={'company_id': company_id, 'plan': plan},
            subscription_data={
                'metadata': {'company_id': company_id, 'plan': plan}
            },
            allow_promotion_codes=True,
        )
        return jsonify({"url": checkout.url})

    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════
# BILLING PORTAL — Manage subscription
# ═══════════════════════════════════════════
@stripe_bp.route('/api/stripe/portal', methods=['POST'])
def billing_portal():
    if 'employee_id' not in session:
        return jsonify({"error": "Non authentifié"}), 401
    if session.get('role') != 'admin':
        return jsonify({"error": "Seul un admin peut gérer la facturation"}), 403

    with get_db() as conn:
        company = q1(f"SELECT * FROM companies WHERE id={PH}", (session['company_id'],), conn)

    if not company or not company.get('stripe_customer_id'):
        return jsonify({"error": "Aucun abonnement actif"}), 404

    try:
        portal = stripe.billing_portal.Session.create(
            customer=company['stripe_customer_id'],
            return_url=f"{APP_URL}/app"
        )
        return jsonify({"url": portal.url})
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════
# WEBHOOK — Handle Stripe events
# ═══════════════════════════════════════════
@stripe_bp.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature')

    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        else:
            event = stripe.Event.construct_from(request.json, stripe.api_key)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event['type']
    data_obj = event['data']['object']

    if event_type == 'checkout.session.completed':
        handle_checkout_completed(data_obj)
    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data_obj)
    elif event_type == 'customer.subscription.deleted':
        handle_subscription_deleted(data_obj)
    elif event_type == 'invoice.payment_failed':
        handle_payment_failed(data_obj)

    return jsonify({"received": True})

def handle_checkout_completed(session_obj):
    company_id = session_obj.get('metadata', {}).get('company_id')
    plan = session_obj.get('metadata', {}).get('plan', 'starter')
    subscription_id = session_obj.get('subscription')
    customer_id = session_obj.get('customer')

    if not company_id:
        return

    config = PLAN_CONFIG.get(plan, PLAN_CONFIG['starter'])
    with get_db() as conn:
        ex(f"""UPDATE companies SET
               plan={PH}, max_employees={PH},
               stripe_customer_id={PH}, stripe_subscription_id={PH}
               WHERE id={PH}""",
           (plan, config['max_employees'], customer_id, subscription_id, company_id), conn)
    print(f"[Stripe] Company {company_id} upgraded to {plan}")

def handle_subscription_updated(subscription):
    company_id = subscription.get('metadata', {}).get('company_id')
    if not company_id:
        # Try to find by customer ID
        customer_id = subscription.get('customer')
        with get_db() as conn:
            co = q1(f"SELECT id FROM companies WHERE stripe_customer_id={PH}", (customer_id,), conn)
        if co:
            company_id = co['id']
        else:
            return

    # Determine plan from price
    plan = 'starter'
    items = subscription.get('items', {}).get('data', [])
    if items:
        price_id = items[0].get('price', {}).get('id', '')
        for p, pid in STRIPE_PRICES.items():
            if pid == price_id:
                plan = p
                break

    status = subscription.get('status')
    config = PLAN_CONFIG.get(plan, PLAN_CONFIG['starter'])

    with get_db() as conn:
        if status in ('active', 'trialing'):
            ex(f"UPDATE companies SET plan={PH}, max_employees={PH}, stripe_subscription_id={PH} WHERE id={PH}",
               (plan, config['max_employees'], subscription['id'], company_id), conn)
        elif status in ('past_due', 'unpaid'):
            # Keep plan but flag — could add a warning column
            ex(f"UPDATE companies SET stripe_subscription_id={PH} WHERE id={PH}",
               (subscription['id'], company_id), conn)

    print(f"[Stripe] Subscription updated: company={company_id}, plan={plan}, status={status}")

def handle_subscription_deleted(subscription):
    customer_id = subscription.get('customer')
    with get_db() as conn:
        co = q1(f"SELECT id FROM companies WHERE stripe_customer_id={PH}", (customer_id,), conn)
        if co:
            # Downgrade to starter (free-ish limits)
            ex(f"UPDATE companies SET plan='starter', max_employees=10, stripe_subscription_id=NULL WHERE id={PH}",
               (co['id'],), conn)
            print(f"[Stripe] Company {co['id']} downgraded to starter (subscription cancelled)")

def handle_payment_failed(invoice):
    customer_id = invoice.get('customer')
    print(f"[Stripe] Payment failed for customer {customer_id}")

# ═══════════════════════════════════════════
# PLAN STATUS API
# ═══════════════════════════════════════════
@stripe_bp.route('/api/stripe/status')
def stripe_status():
    if 'employee_id' not in session:
        return jsonify({"error": "Non authentifié"}), 401

    with get_db() as conn:
        company = q1(f"SELECT * FROM companies WHERE id={PH}", (session['company_id'],), conn)
        emp_count = q1(f"SELECT COUNT(*) as c FROM employees WHERE company_id={PH} AND is_active=TRUE",
                       (session['company_id'],), conn)

    sub_status = None
    current_period_end = None
    if company.get('stripe_subscription_id'):
        try:
            sub = stripe.Subscription.retrieve(company['stripe_subscription_id'])
            sub_status = sub.status
            current_period_end = sub.current_period_end
        except:
            pass

    return jsonify({
        "plan": company['plan'],
        "maxEmployees": company['max_employees'],
        "currentEmployees": emp_count['c'] if emp_count else 0,
        "subscriptionStatus": sub_status,
        "currentPeriodEnd": current_period_end,
        "hasStripe": bool(company.get('stripe_customer_id')),
    })
