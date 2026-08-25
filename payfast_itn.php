<?php
/**
 * Moya — PayFast ITN (Instant Transaction Notification) handler
 * ----------------------------------------------------------------------------
 * Activates the buyer's paid add-ons the moment a payment clears.
 *
 * Security model (do NOT relax):
 *   1. POST-back is verified with PayFast's /eng/query/validate endpoint.
 *   2. merchant_id must match our config.
 *   3. The expected amount is recomputed SERVER-SIDE from the user's stored
 *      plan (moyaMonthlyOwed) — the amount in the ITN is only used to confirm
 *      it matches what we billed. We never trust a client-supplied price.
 *   4. payment_status must be COMPLETE.
 *
 * Always responds 200 to PayFast (except clearly malformed/mismatched posts,
 * which still return 200 after logging so PayFast stops retrying).
 */

error_reporting(0);
require_once __DIR__ . '/moya_payfast_config.php';
require_once __DIR__ . '/moya.php';

$pfData = $_POST;
if (empty($pfData)) {
    http_response_code(400);
    echo 'No data';
    exit;
}

// Build the parameter string PayFast expects for validation.
// Exclude the signature; urlencode + trim each value, join with '&'.
$pfParamString = '';
foreach ($pfData as $key => $val) {
    if ($key === 'signature') continue;
    $pfParamString .= $key . '=' . urlencode(trim($val)) . '&';
}
$pfParamString = rtrim($pfParamString, '&');

// Verify the ITN with PayFast.
$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, PF_VALIDATE_URL);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $pfParamString);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 2);
curl_setopt($ch, CURLOPT_TIMEOUT, 20);
$response = curl_exec($ch);
curl_close($ch);

if (trim((string)$response) !== 'VALID') {
    file_put_contents(__DIR__ . '/itn_log.txt', date('c') . " INVALID validate response: " . $response . "\n", FILE_APPEND);
    http_response_code(400);
    echo 'INVALID';
    exit;
}

// Only act on completed payments.
if (($pfData['payment_status'] ?? '') !== 'COMPLETE') {
    http_response_code(200);
    echo 'OK';
    exit;
}

// Merchant must be us.
if (($pfData['merchant_id'] ?? '') !== PF_MERCHANT_ID) {
    file_put_contents(__DIR__ . '/itn_log.txt', date('c') . " merchant mismatch\n", FILE_APPEND);
    http_response_code(200);
    echo 'OK';
    exit;
}

// Resolve the user from custom_str1 (set in the checkout redirect).
$userId = (int)($pfData['custom_str1'] ?? 0);
if (!$userId) {
    http_response_code(200);
    echo 'OK';
    exit;
}
$stmt = db()->prepare("SELECT * FROM users WHERE id = ?");
$stmt->execute([$userId]);
$user = $stmt->fetch();
if (!$user) {
    http_response_code(200);
    echo 'OK';
    exit;
}

// SERVER-SIDE amount check — authoritative, never trusts client input.
$expected = moyaMonthlyOwed($user);
$gross    = (float)($pfData['amount_gross'] ?? 0);
if (abs($gross - $expected) > 1.0) {
    // Mismatch → flag for manual review, do not silently grant access.
    db()->prepare("UPDATE users SET payment_status = 'review', payfast_txn = ? WHERE id = ?")
        ->execute([$pfData['payment_id'] ?? '', $userId]);
    @mail('sales@mylo.co.za', 'Moya — ITN amount mismatch',
        "User $userId: expected R$expected, received R$gross (txn " . ($pfData['payment_id'] ?? '?') . ")");
    http_response_code(200);
    echo 'OK';
    exit;
}

// Activate the paid period (1 month of access). For recurring billing,
// wire PayFast subscriptions / adhoc payments — this grants a single month.
db()->prepare("UPDATE users SET payment_status = 'active', paid_until = datetime('now','+1 month'), payfast_txn = ? WHERE id = ?")
    ->execute([$pfData['payment_id'] ?? '', $userId]);

http_response_code(200);
echo 'OK';
