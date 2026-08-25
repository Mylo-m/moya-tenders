<?php
/**
 * Moya — PayFast configuration
 * ----------------------------------------------------------------------------
 * SANDBOX by default. Before going LIVE:
 *   1. Set PF_SANDBOX to false
 *   2. Replace PF_MERCHANT_ID / PF_MERCHANT_KEY with your live credentials
 *   3. Confirm PF_NOTIFY_URL is reachable over HTTPS (no Basic-Auth wall,
 *      no redirect) — PayFast must be able to POST the ITN to it.
 *
 * SECURITY NOTE: prices are NEVER sent from the browser. This file only holds
 * identity + endpoints. The billable amount is recomputed server-side in
 * moya.php (moyaMonthlyOwed) from the user's stored plan.
 */
define('PF_SANDBOX', true);
define('PF_MERCHANT_ID', 'REPLACE_ME');
define('PF_MERCHANT_KEY', 'REPLACE_ME');

define('PF_RETURN_URL',  'https://www.mylo.co.za/moya_data/account.php');
define('PF_CANCEL_URL',  'https://www.mylo.co.za/moya_data/account.php');
define('PF_NOTIFY_URL',  'https://www.mylo.co.za/moya_data/payfast_itn.php');

define('PF_HOST',         PF_SANDBOX ? 'https://sandbox.payfast.co.za' : 'https://www.payfast.co.za');
define('PF_PROCESS_URL',  PF_HOST . '/eng/process');
define('PF_VALIDATE_URL', PF_HOST . '/eng/query/validate');
