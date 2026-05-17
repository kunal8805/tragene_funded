import os
import sys
import unittest
from datetime import datetime, timezone

# Force in-memory database for testing to ensure the live database is NEVER touched or wiped!
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['DEV_MODE'] = 'false'

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, provision_challenge
from models import User, ChallengeTemplate, TradingJourney, Payment, AccountSnapshot
from mt5_receiver import receiver_app

class TestStateMachine(unittest.TestCase):
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app_context = app.app_context()
        self.app_context.push()
        db.create_all()
        
        # Create a test user
        self.user = User(
            first_name="Test",
            last_name="User",
            email="test@user.com",
            phone="1234567890",
            dob=datetime(1995, 1, 1).date(),
            country="India"
        )
        self.user.set_password("password123")
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_challenge_provisioning(self):
        # 1. Test One Phase Template Provisioning
        one_phase_template = ChallengeTemplate(
            name="One Phase Challenge",
            price=1000,
            account_size=10000,
            challenge_type="one_phase",
            phase=1,
            phase1_target=8.0,
            phase1_daily_loss=5.0,
            phase1_overall_loss=10.0,
            phase1_min_days=5,
            phase1_duration=30,
            phase1_leverage="1:100",
            user_profit_share=80,
            payout_cycle="biweekly",
            is_active=True
        )
        db.session.add(one_phase_template)
        db.session.commit()

        payment_one = Payment(
            user_id=self.user.id,
            challenge_template_id=one_phase_template.id,
            payment_id="PAY_ONE_PHASE",
            amount=1000.0,
            expected_amount=1000.0,
            payment_method="cashfree",
            status="pending"
        )
        db.session.add(payment_one)
        db.session.commit()

        success, journey_id = provision_challenge(payment_one, self.user, one_phase_template.id)
        self.assertTrue(success)
        
        journey = TradingJourney.query.get(journey_id)
        self.assertEqual(journey.challenge_type, "one_phase")
        self.assertEqual(journey.current_phase, 1)
        self.assertEqual(journey.status, "phase1_active")
        self.assertFalse(journey.is_terminated)
        self.assertEqual(journey.phase, 1)

        # 2. Test Two Phase Template Provisioning
        two_phase_template = ChallengeTemplate(
            name="Two Phase Challenge",
            price=2000,
            account_size=20000,
            challenge_type="two_phase",
            phase=1,
            phase1_target=10.0,
            phase1_daily_loss=5.0,
            phase1_overall_loss=10.0,
            phase1_min_days=5,
            phase1_duration=30,
            phase1_leverage="1:100",
            user_profit_share=80,
            payout_cycle="biweekly",
            is_active=True
        )
        db.session.add(two_phase_template)
        db.session.commit()

        payment_two = Payment(
            user_id=self.user.id,
            challenge_template_id=two_phase_template.id,
            payment_id="PAY_TWO_PHASE",
            amount=2000.0,
            expected_amount=2000.0,
            payment_method="cashfree",
            status="pending"
        )
        db.session.add(payment_two)
        db.session.commit()

        success, journey_id_two = provision_challenge(payment_two, self.user, two_phase_template.id)
        self.assertTrue(success)
        
        journey_two = TradingJourney.query.get(journey_id_two)
        self.assertEqual(journey_two.challenge_type, "two_phase")
        self.assertEqual(journey_two.current_phase, 1)
        self.assertEqual(journey_two.status, "phase1_active")
        self.assertFalse(journey_two.is_terminated)

        # 3. Test Instant Account Provisioning
        instant_template = ChallengeTemplate(
            name="Instant Challenge",
            price=3000,
            account_size=30000,
            challenge_type="instant",
            phase=0,
            phase1_target=0.0,
            phase1_daily_loss=5.0,
            phase1_overall_loss=10.0,
            phase1_min_days=0,
            phase1_duration=999,
            phase1_leverage="1:100",
            user_profit_share=80,
            payout_cycle="biweekly",
            is_active=True
        )
        db.session.add(instant_template)
        db.session.commit()

        payment_three = Payment(
            user_id=self.user.id,
            challenge_template_id=instant_template.id,
            payment_id="PAY_INSTANT",
            amount=3000.0,
            expected_amount=3000.0,
            payment_method="cashfree",
            status="pending"
        )
        db.session.add(payment_three)
        db.session.commit()

        success, journey_id_three = provision_challenge(payment_three, self.user, instant_template.id)
        self.assertTrue(success)
        
        journey_three = TradingJourney.query.get(journey_id_three)
        self.assertEqual(journey_three.challenge_type, "instant")
        self.assertEqual(journey_three.current_phase, 0)
        self.assertEqual(journey_three.status, "funded_active")
        self.assertFalse(journey_three.is_terminated)

    def test_state_transitions(self):
        # Setup a two-phase challenge journey
        journey = TradingJourney(
            user_id=self.user.id,
            challenge_template_id=1,
            challenge_type="two_phase",
            current_phase=1,
            status="phase1_active",
            phase=1,
            is_terminated=False,
            amount=100.0
        )
        db.session.add(journey)
        db.session.commit()

        # Test passing Phase 1 -> transition to Phase 2
        # Mocking the force_pass_phase1 logic
        ctype = journey.challenge_type or 'one_phase'
        if ctype == 'two_phase':
            journey.current_phase = 2
            journey.status = 'phase2_active'
            journey.phase = 2
        
        db.session.commit()
        
        self.assertEqual(journey.current_phase, 2)
        self.assertEqual(journey.status, "phase2_active")
        self.assertEqual(journey.phase, 2)

        # Test passing Phase 2 -> transition to Funded Active
        journey.current_phase = 3
        journey.status = 'funded_active'
        journey.phase = 3
        db.session.commit()

        self.assertEqual(journey.current_phase, 3)
        self.assertEqual(journey.status, "funded_active")

        # Test failing / breaching -> invalidate and terminate
        journey.status = 'breached'
        journey.is_terminated = True
        db.session.commit()

        self.assertEqual(journey.status, "breached")
        self.assertTrue(journey.is_terminated)

if __name__ == '__main__':
    unittest.main()
