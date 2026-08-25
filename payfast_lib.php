<?php
/**
 * Moya — PayFast helper library (shared).
 *
 * Used by:
 *   - process_founding_plan.php  (build the redirect to PayFast)
 *   - payfast_itn_founding.php   (verify the Instant Payment Notification)
 *
 * Credentials below are PayFast's PUBLIC SANDBOX test values.
 * To go LIVE: set PF_SANDBOX = false and replace merchant id / key / passphrase.
 * The passphrase is set in your PayFast dashboard (Settings > Integrations).
 *
 * NOTE (2026-08): your existing stub pay_extra_sectors.php points its notify_url
 * at payfast_itn.php which does not exist. This library powers the Founding
 * flow specifically; keep the two flows separate to avoid cross-wiring.
 */

// ---- Toggle: sandbox vs live ----
define('PF_SANDBOX', true);

define('PF_MERCHANT_ID',  '10000100');          // PayFast sandbox test merchant
define('PF_MERCHANT_KEY', '48f12cc48fb4a');     // PayFast sandbox test key
define('PF_PASSPHRASE',  '');                   // set your live passphrase here

define('PF_URL_PROCESS', PF_SANDBOX
    ? 'https://sandbox.payfast.co.za/eng/process'
    : 'https://www.payfast.co.za/eng/process');
define('PF_URL_VALIDATE', PF_SANDBOX
    ? 'https://sandbox.payfast.co.za/eng/query/validate'
    : 'https://www.payfast.co.za/eng/query/validate');

/**
 * Build the PayFast parameter signature (md5) exactly as PayFast expects:
 *  - keys sorted alphabetically (case-insensitive)
 *  - values urlencoded
 *  - passphrase appended (if set), also urlencoded
 * Excludes the 'signature' key itself.
 */
function pfGenerateSignature(array $data, $passphrase = PF_PASSPHRASE) {
    $data = array_filter($data, function ($v, $k) {
        return $k !== 'signature' && $v !== null && $v !== '';
    }, ARRAY_FILTER_USE_BOTH);
    uksort($data, 'strcasecmp');
    $str = '';
    foreach ($data as $k => $v) {
        $str .= $k . '=' . urlencode(trim((string)$v)) . '&';
    }
    $str = rtrim($str, '&');
    if ($passphrase !== '' && $passphrase !== null) {
        $str .= '&passphrase=' . urlencode(trim($passphrase));
    }
    return md5($str);
}

/**
 * Verify an incoming ITN against its signature locally (authoritative).
 */
function pfSignatureValid(array $posted) {
    if (empty($posted['signature'])) return false;
    return hash_equals((string)$posted['signature'], (string)pfGenerateSignature($posted));
}

/**
 * Re-validate the ITN with PayFast's servers (defence in depth).
 * Returns true on a "VALID" response, false otherwise. Never throws.
 */
function pfServerValid(array $posted) {
    $query = [];
    foreach ($posted as $k => $v) {
        $query[] = $k . '=' . urlencode(trim((string)$v));
    }
    $queryStr = implode('&', $query);
    $ch = curl_init();
    curl_setopt($ch, CURLOPT_URL, PF_URL_VALIDATE);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $queryStr);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    curl_setopt($ch, CURLOPT_TIMEOUT, 20);
    $resp = (string)curl_exec($ch);
    curl_close($ch);
    $out = [];
    parse_str($resp, $out);
    return (($out['VALID'] ?? '') === 'YES');
}

/**
 * Write a line to the ITN log for auditing.
 */
function pfLog($msg) {
    $line = date('c') . ' | ' . $msg . "\n";
    @file_put_contents(__DIR__ . '/payfast_itn_founding.log', $line, FILE_APPEND | LOCK_EX);
}
