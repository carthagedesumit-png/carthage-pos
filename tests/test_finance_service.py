import os
import sqlite3
import tempfile
import unittest

from app.core.exceptions import AuthorizationError, ValidationError


class FinanceServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.db=tempfile.NamedTemporaryFile(delete=False);self.db.close();os.environ['CARTHAGE_POS_DB']=self.db.name
        from app.database.db_manager import initialize_database,get_connection
        from tests.support import bootstrap_staff
        initialize_database();self.sessions=bootstrap_staff()
        with get_connection() as conn:self.accounts={r['code']:r['id'] for r in conn.execute('SELECT id,code FROM finance_accounts')}
        from app.finance import finance_service as f
        self.f=f
    def tearDown(self):
        os.environ.pop('CARTHAGE_POS_DB',None);os.unlink(self.db.name)
    def lines(self,debit='1000',credit='4200',amount=100):
        return [{'account_id':self.accounts[debit],'debit':amount},{'account_id':self.accounts[credit],'credit':amount}]
    def test_journal_requires_double_entry_and_balancing(self):
        with self.assertRaises(ValidationError):self.f.create_journal(self.sessions['manager'],'2026-01-10','Bad',self.lines(amount=10)+[{'account_id':self.accounts['6000'],'debit':1}])
        with self.assertRaises(ValidationError):self.f.create_journal(self.sessions['manager'],'2026-01-10','One line',[self.lines()[0]])
        result=self.f.create_journal(self.sessions['manager'],'2026-01-10','Balanced',self.lines(),post=True)
        self.assertEqual(result['journal']['status'],'POSTED');self.assertEqual(sum(x['debit'] for x in result['lines']),sum(x['credit'] for x in result['lines']))
    def test_posted_journals_are_database_immutable(self):
        result=self.f.create_journal(self.sessions['manager'],'2026-01-10','Immutable',self.lines(),post=True)
        from app.database.db_manager import get_connection
        with self.assertRaises(sqlite3.IntegrityError):
            with get_connection() as conn:conn.execute('UPDATE finance_journals SET description=? WHERE id=?',('Changed',result['journal']['id']))
        with self.assertRaises(sqlite3.IntegrityError):
            with get_connection() as conn:conn.execute('DELETE FROM finance_journal_lines WHERE journal_id=?',(result['journal']['id'],))
    def test_expense_approval_posts_ledger_and_statements(self):
        from app.database.db_manager import get_connection
        with get_connection() as conn:category=conn.execute("SELECT id FROM finance_categories WHERE name='General Operating'").fetchone()[0]
        expense=self.f.create_expense(self.sessions['manager'],'2026-02-01',category,75,'Utilities',tax_amount=5,attachment_name='bill.pdf',recurring_rule='MONTHLY')
        journal=self.f.approve_expense(self.sessions['manager'],expense);self.assertEqual(journal['journal']['status'],'POSTED')
        report=self.f.statements(self.sessions['manager']);self.assertEqual(report['profit_loss']['expenses'],75);self.assertEqual(report['profit_loss']['net_profit'],-75)
    def test_cash_reconciliation_adjustment_and_repeatable_sessions(self):
        first=self.f.open_cash(self.sessions['manager'],100);self.f.cash_adjustment(self.sessions['manager'],first,20,'Float added')
        result=self.f.close_cash(self.sessions['manager'],first,118);self.assertEqual(result,{'expected_amount':120.0,'closing_amount':118.0,'variance':-2.0})
        second=self.f.open_cash(self.sessions['manager'],50);self.assertNotEqual(first,second)
    def test_material_cash_variance_requires_explanation(self):
        session_id=self.f.open_cash(self.sessions['manager'],100)
        with self.assertRaises(ValidationError):self.f.close_cash(self.sessions['manager'],session_id,90)
        result=self.f.close_cash(self.sessions['manager'],session_id,90,'Count verified twice')
        self.assertEqual(result['variance'],-10.0)
    def test_cashier_can_reconcile_own_session_but_not_another_cashier_session(self):
        own=self.f.open_cash(self.sessions['cashier'],25)
        self.assertEqual(self.f.close_cash(self.sessions['cashier'],own,25)['variance'],0.0)
        manager_session=self.f.open_cash(self.sessions['manager'],10)
        with self.assertRaises(AuthorizationError):self.f.close_cash(self.sessions['cashier'],manager_session,10)
    def test_tax_inclusive_exclusive_and_exemption(self):
        self.assertEqual(self.f.calculate_tax(100,.1,'EXCLUSIVE'),{'net':100.0,'tax':10.0,'gross':110.0})
        self.assertEqual(self.f.calculate_tax(110,.1,'INCLUSIVE'),{'net':100.0,'tax':10.0,'gross':110.0})
        self.assertEqual(self.f.calculate_tax(110,.1,'EXEMPT'),{'net':110.0,'tax':0.0,'gross':110.0})
    def test_cashier_is_read_only_and_admin_can_lock_period(self):
        self.f.list_accounts(self.sessions['cashier'])
        with self.assertRaises(AuthorizationError):self.f.create_journal(self.sessions['cashier'],'2026-03-01','Denied',self.lines())
        with self.assertRaises(AuthorizationError):self.f.lock_period(self.sessions['manager'],'March','2026-03-01','2026-03-31')
        self.f.lock_period(self.sessions['admin'],'March','2026-03-01','2026-03-31')
        with self.assertRaises(ValidationError):self.f.create_journal(self.sessions['admin'],'2026-03-10','Locked',self.lines())
    def test_store_scoping_keeps_ledgers_separate(self):
        from app.database.db_manager import get_connection
        from auth import UserSession
        with get_connection() as conn:store2=conn.execute("INSERT INTO stores(code,name,is_active) VALUES('SECOND','Second',1)").lastrowid
        admin2=UserSession(self.sessions['admin'].user_id,self.sessions['admin'].username,self.sessions['admin'].full_name,'admin',store2)
        self.f.create_journal(self.sessions['admin'],'2026-04-01','Main',self.lines(amount=25),post=True)
        self.f.create_journal(admin2,'2026-04-01','Second',self.lines(amount=80),store_id=store2,post=True)
        self.assertEqual(self.f.statements(self.sessions['admin'])['profit_loss']['income'],25)
        self.assertEqual(self.f.statements(admin2,store_id=store2)['profit_loss']['income'],80)
        with self.assertRaises(AuthorizationError):self.f.statements(self.sessions['manager'],store_id=store2)


if __name__=='__main__':unittest.main()
