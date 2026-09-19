from copy import deepcopy
from pathlib import Path
import unittest
from kg_rootcause.ingestion import load_dataset
from kg_rootcause.paths import dataset_directory
from kg_rootcause.audit.declines import trace


class DeclineAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset,_=load_dataset(dataset_directory(__file__))
        cls.history=sorted(cls.dataset['tables']['authorization_history'],key=lambda r:(r['timestamp'],r['authorization_id']))
        cls.target=cls.dataset['indexes']['authorization_history']['TR03359']

    def test_railnest_card_and_customer_scope(self):
        result=trace(self.target,self.history)
        self.assertIn('first_card_merchant',result['flags'])
        self.assertNotIn('first_customer_merchant',result['flags'])
        self.assertEqual(result['other_card_merchant_approval_count'],3)
        self.assertEqual(result['account_month_before_cents'],62327)
        self.assertEqual(result['prior_purchase_p95_cents'],10387)
        self.assertIsNone(result['confirmed_decline_reason'])

    def test_equal_and_future_events_excluded(self):
        injected=dict(self.target,authorization_id='FUTURE',status='approved')
        original=trace(self.target,self.history)
        modified=trace(self.target,self.history+[injected])
        self.assertEqual(original,modified)

    def test_current_outcome_does_not_drive_factors(self):
        approved=dict(self.target,status='approved')
        self.assertEqual(trace(self.target,self.history)['flags'],trace(approved,self.history)['flags'])

    def test_current_card_lifecycle_is_not_used(self):
        target=dict(self.target,card_status='blocked')
        self.assertIn('card_inactive',trace(target,self.history)['flags'])
        self.assertNotIn('card_inactive',trace(self.target,self.history)['flags'])

    def test_p95_requires_history(self):
        result=trace(dict(self.target,billing_amount_chf=999999),[])
        self.assertNotIn('amount_above_p95',result['flags'])
        self.assertIn('transaction_limit',result['flags'])
        self.assertTrue(any('Fewer than 20' in s for s in result['missing_evidence']))
