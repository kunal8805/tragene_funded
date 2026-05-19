import sys
sys.path.insert(0, '/home/ubuntu/tragene_funded')

from app import app, db

faqs = [
    ("General", "What is Tragene Funded?", "Tragene Funded is a trading challenge platform where traders can participate in evaluation programs and qualify for funded opportunities."),
    ("General", "Is Tragene Funded available internationally?", "Availability may depend on compliance, supported payment methods, and future platform policies."),
    ("General", "Can I create multiple accounts?", "Creating multiple accounts for abuse, rule evasion, or exploiting platform systems may lead to restrictions."),
    ("General", "Do I need prior trading experience?", "No. Beginners and experienced traders can participate, but understanding risk management is strongly recommended."),
    ("General", "How do I get started?", "Create an account, complete your profile and KYC if required, choose a challenge, and purchase it from the Challenges page."),
    ("Support", "What if I cannot find my answer here?", "Create a support ticket and our team will review your issue."),
    ("Support", "Can I track my support request?", "Yes. Ticket status and conversations can be viewed from your dashboard."),
    ("Support", "What is the fastest way to get help?", "The Help Center ticket system is generally the fastest support channel."),
    ("Support", "Can I email support directly?", "support@tragenefunded.com or tragene.co@gmail.com"),
    ("Support", "How do I contact support?", "Use the Help Center ticket system or contact support@tragenefunded.com"),
    ("KYC & Account", "Can I resubmit KYC?", "Yes. Users can usually resubmit corrected information."),
    ("KYC & Account", "Why was my KYC rejected?", "Common reasons include unclear images, incorrect information, or unsupported documents."),
    ("KYC & Account", "Which documents are accepted?", "Accepted documents are listed on the KYC page."),
    ("KYC & Account", "How long does KYC verification take?", "Verification generally takes between 24–48 business hours."),
    ("KYC & Account", "Why do I need KYC?", "KYC helps maintain security and platform integrity."),
    ("Refunds", "Can suspicious activity affect refunds?", "Yes. Suspicious activity or fraud indicators may lead to investigation before processing."),
    ("Refunds", "Will failed trading performance qualify for refunds?", "No. Trading outcomes or challenge performance do not qualify for refunds."),
    ("Refunds", "How long do refund investigations take?", "Review times vary depending on payment verification and investigation requirements."),
    ("Refunds", "I paid but received no challenge. Can I get a refund?", "We may provide challenge delivery or review the issue according to platform policies."),
    ("Refunds", "When can a refund request be reviewed?", "Refund requests may be reviewed for duplicate payments, technical failures, or service delivery issues."),
    ("Refunds", "Are challenge purchases refundable?", "Challenge purchases are generally non-refundable except in specific eligible situations."),
    ("Payments", "Can I cancel a payment after completion?", "Completed transactions generally cannot be cancelled after successful processing."),
    ("Payments", "Why is my payment pending?", "Some payment methods require extra processing time before final confirmation."),
    ("Payments", "I was charged twice. What should I do?", "Open a support ticket immediately. Duplicate payments may be reviewed and handled accordingly."),
    ("Payments", "Why was my payment marked failed?", "This can happen due to banking issues, payment interruptions, network failures, or gateway issues."),
    ("Payments", "Are payments secure?", "Yes. Payments are processed through secure payment gateway systems."),
    ("Payments", "Which payment methods are supported?", "Supported methods may include UPI, debit cards, credit cards, net banking, and other available payment options."),
    ("Payments", "What payment methods are available?", "Payments are processed securely through Cashfree."),
    ("Challenge & Trading", "Can challenge rules change?", "Platform rules and policies may be updated to improve fairness and platform operations."),
    ("Challenge & Trading", "Where can I see challenge rules?", "Rules are displayed on challenge pages and within your dashboard."),
    ("Challenge & Trading", "What happens if I violate challenge rules?", "Rule violations may result in challenge failure or restrictions according to platform rules."),
    ("Challenge & Trading", "Can I retry a failed challenge?", "Retry policies may vary by challenge type and promotional offers."),
    ("Challenge & Trading", "I paid but did not receive my challenge. What should I do?", "Contact support through the Help Center. If payment succeeded but delivery failed, we will investigate and assist."),
    ("Challenge & Trading", "What happens after successful payment?", "Your challenge should appear in your dashboard after successful processing."),
    ("Challenge & Trading", "What challenge sizes are available?", "Challenge options and account sizes are displayed directly on the challenge page."),
    ("Challenge & Trading", "How do I buy a challenge?", "Go to the Challenges section, select your preferred challenge, and complete payment securely."),
    ("KYC", "How long does KYC take?", "KYC verification usually takes 24–48 hours."),
    ("Challenges", "How do challenge purchases work?", "Select a challenge, complete payment, and your account will be activated automatically."),
]

with app.app_context():
    from models import FAQ
    count = 0
    for category, question, answer in faqs:
        faq = FAQ(category=category, question=question, answer=answer)
        db.session.add(faq)
        count += 1
    db.session.commit()
    print(f"Successfully inserted {count} FAQs!")
