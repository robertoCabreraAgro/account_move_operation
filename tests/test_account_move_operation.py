# Copyright 2018-2019 ForgeFlow, S.L.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging

from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.account_accountant.tests.test_bank_rec_widget_common import (
    TestBankRecWidgetCommon,
)

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestAccountMoveTemplate(TestBankRecWidgetCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.company_2 = cls.env.ref("account_move_operation.demo_company")
        cls.env.user.company_ids |= cls.company
        cls.env.user.company_ids |= cls.company_2
        cls.operation_type = cls.env.ref("account_move_operation.operation_type_cash_return")
        cls.operation_type_2 = cls.env.ref("account_move_operation.operation_type_cash_return_multicompany")
        cls.operation_type_3 = cls.env.ref("account_move_operation.operation_type_cash_return_manual")
        cls.operation_obj = cls.env["account.move.operation"]
        cls.partner = cls.env["res.partner"].create({"name": "Test partner", "company_id": False})
        cls.partner2 = cls.env["res.partner"].create({"name": "Test partner 2", "company_id": False})
        cls.product = cls.env.ref("product.product_product_8")
        cls.payment_term = cls.create_payment_term()
        cls.partner.write({"property_payment_term_id": cls.payment_term.id})
        cls.env.user.company_id = cls.company
        cls.journal_bank = cls.env["account.journal"].search(
            [("company_id", "=", cls.company.id), ("type", "=", "bank")], limit=1
        )
        cls.env["ir.config_parameter"].sudo().set_param("marin.avoid_authorize_debt", "True")

    @classmethod
    def create_payment_term(cls):
        payment_term = cls.env["account.payment.term"].create(
            {
                "name": "Payment Term For Testing",
                "early_discount": False,
                "discount_days": False,
                "discount_percentage": 0,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "value": "percent",
                            "value_amount": 100,
                            "delay_type": "days_after",
                            "nb_days": 0,
                        },
                    ),
                ],
            }
        )
        return payment_term

    def test_01_create_operation(self):
        group = self.env.ref("marin.group_account_debt_manager", False)
        if group:
            self.env.user.groups_id = [(4, group.id)]
        operation = self.operation_obj.create(
            {
                "operation_type_id": self.operation_type.id,
                "currency_id": self.company.currency_id.id,
                "company_id": self.company.id,
            }
        )
        st_line = self._create_st_line(
            1000.0, partner_id=self.partner.id, journal_id=self.journal_bank.id, company_id=self.company.id
        )
        with Form(operation) as form_op:
            form_op.st_line_id = st_line
        form_op.save()
        self.assertEqual(operation.st_line_id, st_line)
        self.assertEqual(operation.partner_id, self.partner)
        with Form(operation) as form_op:
            form_op.partner_id = self.partner2
            form_op.partner_id = self.partner
        form_op.save()
        self.assertFalse(operation.st_line_id)
        operation.st_line_id = st_line

        self.assertEqual(operation.state, "draft")
        operation.action_start()
        self.assertEqual(operation.state, "in_progress")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "ready",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        op_line = self.env["account.move.operation.line"].browse(action.get("context", {}).get("active_ids"))
        wizard = (
            self.env["account.invoice.template.run"]
            .with_context(**action.get("context", {}))
            .create(
                {
                    "template_id": op_line.template_id.id,
                }
            )
        )
        wizard._onchange_template_id()
        wiz_line = wizard.line_ids
        wiz_line.update(
            {
                "product_id": self.product.id,
                "amount": 10.0,
            }
        )
        wizard.generate_move()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "in_progress",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        invoice = self.env["account.move"].browse(action.get("res_id"))
        invoice.action_post()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "ready",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        wizard = self.env["bank.rec.widget"].with_context(action.get("context", {})).new({})
        self.assertRecordValues(wizard, [{"state": "valid"}])
        wizard._action_add_new_amls(invoice.invoice_line_ids)
        wizard._action_validate()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "reconcile",
                },
                {
                    "state": "ready",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        op_line = self.env["account.move.operation.line"].browse(action.get("context", {}).get("active_ids"))
        wizard = (
            self.env["account.invoice.template.run"]
            .with_context(**action.get("context", {}))
            .create(
                {
                    "template_id": op_line.template_id.id,
                }
            )
        )
        wizard._onchange_template_id()
        wizard.update({"post": True})
        wiz_line = wizard.line_ids
        wiz_line.update(
            {
                "amount": 10.0,
            }
        )
        wizard.generate_move()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "reconcile",
                },
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "ready",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        wizard = self.env["account.payment.register"].with_context(**action.get("context", {})).create({})
        wizard._create_payments()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "reconcile",
                },
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "pay",
                },
            ],
        )
        self.assertEqual(operation.state, "done")

    def test_02_cancel_operation(self):
        operation = self.operation_obj.create(
            {
                "operation_type_id": self.operation_type.id,
                "partner_id": self.partner.id,
                "currency_id": self.company.currency_id.id,
            }
        )
        self.assertEqual(operation.state, "draft")
        operation.action_start()
        self.assertEqual(operation.state, "in_progress")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "ready",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        operation.action_cancel()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "cancel",
                },
                {
                    "state": "cancel",
                },
                {
                    "state": "cancel",
                },
                {
                    "state": "cancel",
                },
            ],
        )
        self.assertEqual(operation.state, "cancel")

    def test_03_create_operation_multicompany(self):
        operation = self.operation_obj.create(
            {
                "operation_type_id": self.operation_type_2.id,
                "partner_id": self.partner.id,
                "currency_id": self.company.currency_id.id,
            }
        )
        self.assertEqual(operation.state, "draft")
        operation.action_start()
        self.assertEqual(operation.state, "in_progress")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "ready",
                    "action": "operation",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        operation.action_next_step()
        operation_2 = operation.line_ids[0].created_operation_id
        self.assertTrue(operation_2)
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "in_progress",
                    "action": "operation",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        self.assertEqual(operation_2.state, "in_progress")
        self.assertRecordValues(
            operation_2.line_ids,
            [
                {
                    "state": "ready",
                    "action": "move",
                }
            ],
        )
        op2_line = operation_2.line_ids
        self.assertEqual(op2_line.dest_line_id, operation.line_ids[0])
        action = operation_2.with_company(self.company_2).action_next_step()
        wizard = (
            self.env["account.invoice.template.run"]
            .with_company(self.company_2)
            .with_context(**action.get("context", {}))
            .create({"template_id": op2_line.template_id.id})
        )
        wizard._onchange_template_id()
        wiz_line = wizard.line_ids
        wiz_line.update(
            {
                "product_id": self.product.id,
                "amount": 10.0,
            }
        )
        wizard.generate_move()
        self.assertEqual(op2_line.state, "in_progress")
        action = operation_2.action_next_step()
        invoice = self.env["account.move"].with_company(self.company_2).browse(action.get("res_id"))
        invoice.action_post()
        self.assertEqual(op2_line.state, "done")
        self.assertEqual(operation_2.state, "done")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "operation",
                },
                {
                    "state": "ready",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        op_line = self.env["account.move.operation.line"].browse(action.get("context", {}).get("active_ids"))
        wizard = (
            self.env["account.invoice.template.run"]
            .with_context(**action.get("context", {}))
            .create(
                {
                    "template_id": op_line.template_id.id,
                }
            )
        )
        wizard._onchange_template_id()
        wizard.update({"post": True})
        wiz_line = wizard.line_ids
        wiz_line.update(
            {
                "amount": 10.0,
            }
        )
        wizard.generate_move()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "operation",
                },
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "ready",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        wizard = self.env["account.payment.register"].with_context(**action.get("context", {})).create({})
        wizard._create_payments()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "operation",
                },
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "pay",
                },
            ],
        )
        self.assertEqual(operation.state, "done")

    def test_04_cancel_operation_multicompany(self):
        operation = self.operation_obj.create(
            {
                "operation_type_id": self.operation_type_2.id,
                "partner_id": self.partner.id,
                "currency_id": self.company.currency_id.id,
            }
        )
        self.assertEqual(operation.state, "draft")
        operation.action_start()
        self.assertEqual(operation.state, "in_progress")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "ready",
                    "action": "operation",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        operation.action_next_step()
        operation_2 = operation.line_ids[0].created_operation_id
        self.assertTrue(operation_2)
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "in_progress",
                    "action": "operation",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        self.assertEqual(operation_2.state, "in_progress")
        self.assertRecordValues(
            operation_2.line_ids,
            [
                {
                    "state": "ready",
                    "action": "move",
                }
            ],
        )
        op2_line = operation_2.line_ids
        self.assertEqual(op2_line.dest_line_id, operation.line_ids[0])
        operation_2.action_cancel()
        self.assertEqual(op2_line.state, "cancel")
        self.assertEqual(operation_2.state, "cancel")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "cancel",
                    "action": "operation",
                },
                {
                    "state": "cancel",
                    "action": "move",
                },
                {
                    "state": "cancel",
                    "action": "pay",
                },
            ],
        )
        self.assertEqual(operation.state, "cancel")

    def test_05_account_operation_errors(self):
        operation = self.operation_obj.create(
            {
                "operation_type_id": self.operation_type_2.id,
                "currency_id": self.company.currency_id.id,
            }
        )
        with self.assertRaisesRegex(UserError, "Please set a partner before starting operation."):
            operation.action_start()
        self.assertEqual(operation.state, "draft")
        operation.action_done()
        self.assertEqual(operation.state, "draft")
        operation.action_next_step()
        self.assertEqual(operation.state, "draft")

    def test_06_create_operation_manual(self):
        group = self.env.ref("marin.group_account_debt_manager", False)
        if group:
            self.env.user.groups_id = [(4, group.id)]
        operation = self.operation_obj.create(
            {
                "operation_type_id": self.operation_type_3.id,
                "currency_id": self.company.currency_id.id,
                "company_id": self.company.id,
            }
        )
        st_line = self._create_st_line(
            1000.0, partner_id=self.partner.id, journal_id=self.journal_bank.id, company_id=self.company.id
        )
        with Form(operation) as form_op:
            form_op.st_line_id = st_line
        form_op.save()
        self.assertEqual(operation.st_line_id, st_line)
        self.assertEqual(operation.partner_id, self.partner)
        with Form(operation) as form_op:
            form_op.partner_id = self.partner2
            form_op.partner_id = self.partner
        form_op.save()
        self.assertFalse(operation.st_line_id)
        operation.st_line_id = st_line

        self.assertEqual(operation.state, "draft")
        operation.action_start()
        self.assertEqual(operation.state, "in_progress")
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "ready",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        op_line = self.env["account.move.operation.line"].browse(action.get("context", {}).get("active_ids"))
        wizard = (
            self.env["account.invoice.template.run"]
            .with_context(**action.get("context", {}))
            .create(
                {
                    "template_id": op_line.template_id.id,
                }
            )
        )
        wizard._onchange_template_id()
        wiz_line = wizard.line_ids
        wiz_line.update(
            {
                "product_id": self.product.id,
                "amount": 10.0,
            }
        )
        wizard.generate_move()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "in_progress",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        invoice = self.env["account.move"].browse(action.get("res_id"))
        invoice.action_post()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "ready",
                    "action": "reconcile",
                },
                {
                    "state": "waiting",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        wizard = self.env["account.move.operation.reconcile"].with_context(action.get("context", {})).new({})
        wizard.update(
            {
                "partner_id": operation.partner_id.id,
                "move_id": invoice.id,
                "line_id": operation.line_ids[1].id,
                "st_line_id": operation.st_line_id.id,
            }
        )
        action = wizard.action_open_reconcile()
        wizard = self.env["bank.rec.widget"].with_context(action.get("context", {})).new({})
        self.assertRecordValues(wizard, [{"state": "valid"}])
        wizard._action_add_new_amls(invoice.invoice_line_ids)
        wizard._action_validate()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "reconcile",
                },
                {
                    "state": "ready",
                    "action": "move",
                },
                {
                    "state": "waiting",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        op_line = self.env["account.move.operation.line"].browse(action.get("context", {}).get("active_ids"))
        wizard = (
            self.env["account.invoice.template.run"]
            .with_context(**action.get("context", {}))
            .create(
                {
                    "template_id": op_line.template_id.id,
                }
            )
        )
        wizard._onchange_template_id()
        wizard.update({"post": True})
        wiz_line = wizard.line_ids
        wiz_line.update(
            {
                "amount": 10.0,
            }
        )
        wizard.generate_move()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "reconcile",
                },
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "ready",
                    "action": "pay",
                },
            ],
        )
        action = operation.action_next_step()
        wizard = self.env["account.move.operation.payment"].with_context(action.get("context", {})).new({})
        wizard.update(
            {
                "move_id": operation.line_ids[2].move_id.id,
                "line_id": operation.line_ids[3].id,
            }
        )
        action = wizard.action_open_register_payment()
        wizard = self.env["account.payment.register"].with_context(**action.get("context", {})).create({})
        wizard._create_payments()
        self.assertRecordValues(
            operation.line_ids,
            [
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "reconcile",
                },
                {
                    "state": "done",
                    "action": "move",
                },
                {
                    "state": "done",
                    "action": "pay",
                },
            ],
        )
        self.assertEqual(operation.state, "done")
