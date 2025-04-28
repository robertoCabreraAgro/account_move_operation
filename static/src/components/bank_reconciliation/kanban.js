import {patch} from "@web/core/utils/patch";

import {BankRecKanbanController} from "@account_accountant/components/bank_reconciliation/kanban";

patch(BankRecKanbanController.prototype, {
    async actionOperation() {
        await this.execProtectedBankRecAction(async () => {
            await this.withNewState(async (newState) => {
                const {return_todo_command: actionData} = await this.onchange(newState, "account_operation");
                if (actionData) {
                    this.action.doAction(actionData);
                }
            });
        });
    },
});
