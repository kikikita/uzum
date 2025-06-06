import pandas as pd
from datetime import timedelta

DATA_DIR = 'data'
ORDERS_FILE = f"{DATA_DIR}/result.csv"
SCHEDULE_FILE = f"{DATA_DIR}/schedule_before_day_second_payment_razum_ai.xlsx"
REFILL1_FILE = f"{DATA_DIR}/refill_with_error_codes_razum_ai1.xlsx"
REFILL2_FILE = f"{DATA_DIR}/refill_with_error_codes_razum_ai2.xlsx"


def load_data():
    orders = pd.read_csv(ORDERS_FILE, parse_dates=['order_created_dt'])
    schedule = pd.read_excel(SCHEDULE_FILE, sheet_name=0, engine='openpyxl',
                             parse_dates=['plan_payment_dt'])
    refill1 = pd.read_excel(REFILL1_FILE, sheet_name=0, engine='openpyxl',
                            parse_dates=['transaction_dt'])
    refill2 = pd.read_excel(REFILL2_FILE, sheet_name=0, engine='openpyxl',
                            parse_dates=['transaction_dt'])
    refills = pd.concat([refill1, refill2], ignore_index=True)
    return orders, schedule, refills


def assign_payments(plan_df: pd.DataFrame, tx_df: pd.DataFrame) -> pd.DataFrame:
    """Sequentially match successful transactions to planned payments."""
    plan_df = plan_df.sort_values('plan_payment_dt').reset_index(drop=True)
    tx_df = tx_df.sort_values('transaction_dt').reset_index(drop=True)
    payment_dates = []
    j = 0
    for _ in range(len(plan_df)):
        if j < len(tx_df):
            payment_dates.append(tx_df.loc[j, 'transaction_dt'])
            j += 1
        else:
            payment_dates.append(pd.NaT)
    plan_df = plan_df.copy()
    plan_df['payment_dt'] = payment_dates
    return plan_df


def compute_targets(order_row, plan_df, success_df):
    order_dt = order_row['order_created_dt']
    horizon1 = order_dt + timedelta(days=30)
    horizon2 = order_dt + timedelta(days=60)

    plan_df = assign_payments(plan_df, success_df)

    # identify payments that should have been made by each horizon
    cond1_date = plan_df['plan_payment_dt'] <= horizon1
    cond2_date = plan_df['plan_payment_dt'] <= horizon2

    unpaid_h1 = plan_df['payment_dt'].isna() | (plan_df['payment_dt'] > horizon1)
    unpaid_h2 = plan_df['payment_dt'].isna() | (plan_df['payment_dt'] > horizon2)

    cond1 = cond1_date & unpaid_h1
    cond2 = cond2_date & unpaid_h2
    overdue_amount_1m = plan_df.loc[cond1, 'debt'].sum()
    overdue_amount_2m = plan_df.loc[cond2, 'debt'].sum()

    overdue_500r_prob_1m = overdue_amount_1m > 500
    overdue_500r_prob_2m = overdue_amount_2m > 500

    no_success_1m = success_df[success_df['transaction_dt'] <= horizon1].empty
    no_success_2m = success_df[success_df['transaction_dt'] <= horizon2].empty

    return {
        'order_id': order_row['order_id'],
        'overdue_amount_1m': overdue_amount_1m,
        'overdue_amount_2m': overdue_amount_2m,
        'overdue_500r_prob_1m': overdue_500r_prob_1m,
        'overdue_500r_prob_2m': overdue_500r_prob_2m,
        'no_successful_payment_prob_1m': no_success_1m,
        'no_successful_payment_prob_2m': no_success_2m,
    }


def main():
    orders, schedule, refills = load_data()
    success_tx = refills[refills['status'] == 'success']

    target_rows = []
    schedule_grouped = schedule.groupby('order_id')
    tx_grouped = success_tx.groupby('order_id')

    for _, order_row in orders.iterrows():
        order_id = order_row['order_id']
        plan_df = schedule_grouped.get_group(order_id) if order_id in schedule_grouped.groups else pd.DataFrame(columns=['plan_payment_dt', 'debt'])
        success_df = tx_grouped.get_group(order_id) if order_id in tx_grouped.groups else pd.DataFrame(columns=['transaction_dt'])
        targets = compute_targets(order_row, plan_df, success_df)
        target_rows.append(targets)

    targets_df = pd.DataFrame(target_rows)
    result = orders.merge(targets_df, on='order_id', how='left')
    result.to_csv(f"{DATA_DIR}/results_with_targets.csv", index=False)


if __name__ == "__main__":
    main()
