<?php
/**
 * Moya — Compliance Engine (shared library)
 * Used by compliance_engine.php (test/demo) and compliance.php (logged-in client UI).
 * Single source of truth for the ZA / KE rule sets + readiness evaluation.
 *
 * INTERNAL TRACKER model: no public gov verification API exists for SARS / CSD /
 * KRA / AGPO, so clients record cert number + expiry and the engine validates
 * format, tracks validity/expiry, and scores bid-readiness.
 */

if (!function_exists('cdb')) {
    function cdb() {
        static $pdo = null;
        if ($pdo === null) {
            $pdo = new PDO('sqlite:' . DB_PATH);
            $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
            $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        }
        return $pdo;
    }
}

if (!function_exists('ensure_compliance_tables')) {
    function ensure_compliance_tables() {
        $db = cdb();
        $db->exec("
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                country_code TEXT NOT NULL,
                legal_name TEXT NOT NULL,
                registration_no TEXT,
                tax_no TEXT,
                sector TEXT,
                contact_email TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS certificates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL,
                country_code TEXT NOT NULL,
                cert_key TEXT NOT NULL,
                cert_number TEXT,
                cert_level TEXT,
                issued_date TEXT,
                expiry_date TEXT,
                status TEXT DEFAULT 'unknown',
                created_at TEXT DEFAULT (datetime('now'))
            );
        ");
    }
}

if (!function_exists('compliance_registry')) {
    function compliance_registry() {
        return [
            'ZA' => [
                'label' => 'South Africa',
                'authority' => 'National Treasury / SARS / CIDB',
                'certs' => [
                    'csd' => ['label'=>'CSD Registration (Central Supplier Database)','authority'=>'National Treasury','regex'=>'/^[A-Za-z0-9]{6,20}$/','required'=>true,'expiry'=>true,'hint'=>'CSD supplier registration number on the National Treasury portal.'],
                    'tax_clearance' => ['label'=>'Tax Clearance PIN (SARS)','authority'=>'SARS','regex'=>'/^[0-9]{9,10}$/','required'=>true,'expiry'=>true,'hint'=>'SARS Tax Compliance Status PIN; valid 12 months from issue.'],
                    'bbbee' => ['label'=>'B-BBEE Status (Certificate or Affidavit)','authority'=>'B-BBEE Commission','regex'=>'/^(1|2|3|4|5|8)$/','format_field'=>'cert_level','required'=>true,'expiry'=>true,'hint'=>'Contributor level 1-5 or 8; or sworn affidavit (EME/QSE).'],
                    'cidb' => ['label'=>'CIDB Grading (Construction/Infrastructure)','authority'=>'CIDB','regex'=>'/^(9|8|7|6|5|4|3|2|1)\s?(GB|CE|EB|SB|SP|SD|SQ|SM)$/','format_field'=>'cert_level','required'=>false,'expiry'=>true,'conditional'=>'construction','hint'=>'e.g. 9GB. Required only for construction / infrastructure bids.'],
                ],
            ],
            'KE' => [
                'label' => 'Kenya',
                'authority' => 'KRA / BRS / Treasury (PPADA)',
                'certs' => [
                    'kra_tcc' => ['label'=>'KRA Tax Compliance Certificate (iTax)','authority'=>'KRA','regex'=>'/^[A-Z]{1}[0-9]{9}[A-Z]{1}$/','required'=>true,'expiry'=>true,'hint'=>'KRA PIN (e.g. A123456789B) + TCC valid 12 months via iTax.'],
                    'brs' => ['label'=>'BRS Registration No.','authority'=>'BRS Kenya','regex'=>'/^(CPR|[A-Z]{1,3})[-]?[0-9]{5,7}$/','required'=>true,'expiry'=>false,'hint'=>'BRS registration number from e-citizen / BRS portal.'],
                    'agpo' => ['label'=>'AGPO Certificate (Youth / Women / PWD)','authority'=>'Treasury (AGPO)','regex'=>'/^(YOUTH|WOMEN|PWD)[-]?[A-Z0-9]{4,15}$/','format_field'=>'cert_level','required'=>false,'expiry'=>true,'hint'=>'Access to Government Procurement Opportunities cert for Youth, Women, or PWD.'],
                ],
            ],
        ];
    }
}

if (!function_exists('c_parse_date')) {
    function c_parse_date($s) {
        if (!$s) return null;
        foreach (['Y-m-d','d/m/Y','d M Y'] as $fmt) {
            $d = DateTime::createFromFormat($fmt, $s);
            if ($d) return $d;
        }
        return null;
    }
}

if (!function_exists('c_evaluate_cert')) {
    function c_evaluate_cert($spec, $row) {
        $value = isset($row['cert_number']) ? trim($row['cert_number']) : '';
        if (!$row || !$value) return ['status'=>'missing','msg'=>'Not recorded','valid'=>false];
        $fmt_field = $spec['format_field'] ?? 'cert_number';
        $fmt_val = ($fmt_field === 'cert_level' && isset($row['cert_level'])) ? trim($row['cert_level']) : $value;
        if (isset($spec['regex']) && $fmt_val && !preg_match($spec['regex'], $fmt_val)) {
            return ['status'=>'invalid','msg'=>'Format invalid for '.$spec['label'],'valid'=>false];
        }
        if (!empty($spec['expiry'])) {
            $exp = c_parse_date($row['expiry_date'] ?? '');
            if (!$exp) return ['status'=>'unknown','msg'=>'No expiry date recorded','valid'=>false];
            $today = new DateTime();
            if ($exp < $today) return ['status'=>'expired','msg'=>'Expired '.$exp->format('Y-m-d'),'valid'=>false];
            $diff = $today->diff($exp)->days;
            if ($diff <= 30) return ['status'=>'expiring','msg'=>'Expires '.$exp->format('Y-m-d').' (<=30d)','valid'=>true];
            return ['status'=>'valid','msg'=>'Valid to '.$exp->format('Y-m-d'),'valid'=>true];
        }
        return ['status'=>'valid','msg'=>'Recorded (no expiry)','valid'=>true];
    }
}

if (!function_exists('c_evaluate_supplier')) {
    function c_evaluate_supplier($id) {
        $db = cdb();
        $sup = $db->query("SELECT * FROM suppliers WHERE id=$id")->fetch();
        if (!$sup) return null;
        $cc = $sup['country_code'];
        $reg = compliance_registry()[$cc];
        $certs = $db->query("SELECT * FROM certificates WHERE supplier_id=$id")->fetchAll();
        $by_key = [];
        foreach ($certs as $c) $by_key[$c['cert_key']] = $c;
        $results = [];
        foreach ($reg['certs'] as $key => $spec) {
            $row = $by_key[$key] ?? null;
            $ev = c_evaluate_cert($spec, $row);
            $conditional = $spec['conditional'] ?? null;
            $applicable = true;
            if ($conditional) $applicable = ($sup['sector'] === $conditional);
            $req = !empty($spec['required']);
            $results[] = [
                'key'=>$key,'label'=>$spec['label'],'authority'=>$spec['authority'],
                'required'=>$req,'conditional'=>$conditional,'applicable'=>$applicable,
                'status'=>$ev['status'],'msg'=>$ev['msg'],
                'valid'=>$ev['valid'] && ($applicable || !$req),
                'hint'=>$spec['hint'],
            ];
        }
        $needed = array_filter($results, fn($r)=>$r['required'] && $r['applicable']);
        $n = count($needed);
        $passed = count(array_filter($needed, fn($r)=>in_array($r['status'],['valid','expiring'])));
        $score = $n ? round(100*$passed/$n,1) : 100.0;
        $gaps = array_filter($results, fn($r)=>in_array($r['status'],['missing','invalid','expired']) && $r['required'] && $r['applicable']);
        return [
            'legal_name'=>$sup['legal_name'],'country'=>$reg['label'],'country_code'=>$cc,
            'authority'=>$reg['authority'],'score'=>$score,'ready'=>($score>=100 && !$gaps),
            'certs'=>$results,'gaps'=>array_values($gaps),
        ];
    }
}

if (!function_exists('c_get_or_create_supplier')) {
    function c_get_or_create_supplier($user_id, $country_code) {
        $db = cdb();
        $row = $db->query("SELECT * FROM suppliers WHERE user_id=$user_id")->fetch();
        if ($row) return $row;
        $u = $db->query("SELECT name,email,company,sector,country_code FROM users WHERE id=$user_id")->fetch();
        $cc = $country_code ?: ($u['country_code'] ?? 'ZA');
        $db->prepare("INSERT INTO suppliers (user_id,country_code,legal_name,registration_no,tax_no,sector,contact_email) VALUES (?,?,?,?,?,?,?)")
            ->execute([$user_id, $cc, $u['company'] ?: $u['name'], '', '', $u['sector'], $u['email']]);
        return $db->query("SELECT * FROM suppliers WHERE user_id=$user_id")->fetch();
    }
}

if (!function_exists('c_status_flag')) {
    function c_status_flag($s) {
        return [
            'valid'=>'✅','expiring'=>'⚠️','expired'=>'❌',
            'missing'=>'❌','invalid'=>'❌','unknown'=>'❓'
        ][$s] ?? '?';
    }
}
