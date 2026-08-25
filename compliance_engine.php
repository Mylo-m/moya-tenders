<?php
/**
 * Moya — Compliance Engine (Test UI)
 * Self-contained: creates suppliers/certificates tables on moya.db,
 * seeds 3 demo suppliers (ZA construction, KE, ZA expired-tax), and renders a
 * per-country readiness report.
 *
 * Country switching demonstrates dynamic ZA (CSD/SARS/B-BBEE/CIDB) vs
 * KE (KRA/BRS/AGPO) rule sets.
 *
 * No public gov verification API exists for SARS/KRA/CSD/AGPO, so this is an
 * INTERNAL TRACKER: the client records cert number + expiry, the engine
 * validates format, tracks validity/expiry, and scores bid-readiness.
 */

define('DB_PATH', __DIR__ . '/moya.db');

function db() {
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . DB_PATH);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    }
    return $pdo;
}

function ensure_compliance_tables() {
    $db = db();
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

// ----- Registry (mirrors compliance.py) -----
function registry() {
    return [
        'ZA' => [
            'label' => 'South Africa',
            'authority' => 'National Treasury / SARS / CIDB',
            'certs' => [
                'csd' => ['label'=>'CSD Registration (Central Supplier Database)','authority'=>'National Treasury','regex'=>'/^[A-Za-z0-9]{6,20}$/','required'=>true,'expiry'=>true,'hint'=>'CSD supplier registration number.'],
                'tax_clearance' => ['label'=>'Tax Clearance PIN (SARS)','authority'=>'SARS','regex'=>'/^[0-9]{9,10}$/','required'=>true,'expiry'=>true,'hint'=>'SARS Tax Compliance Status PIN; valid 12 months.'],
                'bbbee' => ['label'=>'B-BBEE Status (Certificate or Affidavit)','authority'=>'B-BBEE Commission','regex'=>'/^(1|2|3|4|5|8)$/','format_field'=>'cert_level','required'=>true,'expiry'=>true,'hint'=>'Contributor level 1-5 or 8; or sworn affidavit.'],
                'cidb' => ['label'=>'CIDB Grading (Construction/Infrastructure)','authority'=>'CIDB','regex'=>'/^(9|8|7|6|5|4|3|2|1)\s?(GB|CE|EB|SB|South)\b/','format_field'=>'cert_level','required'=>false,'expiry'=>true,'conditional'=>'construction','hint'=>'e.g. 9GB. Needed only for construction/infra bids.'],
            ],
        ],
        'KE' => [
            'label' => 'Kenya',
            'authority' => 'KRA / BRS / Treasury (PPADA)',
            'certs' => [
                'kra_tcc' => ['label'=>'KRA Tax Compliance Certificate (iTax)','authority'=>'KRA','regex'=>'/^[A-Z]{1}[0-9]{9}[A-Z]{1}$/','required'=>true,'expiry'=>true,'hint'=>'KRA PIN (A123456789B) + TCC valid 12 months.'],
                'brs' => ['label'=>'BRS Registration No.','authority'=>'BRS Kenya','regex'=>'/^(CPR|[A-Z]{1,3})[-]?[0-9]{5,7}$/','required'=>true,'expiry'=>false,'hint'=>'BRS registration number from e-citizen.'],
                'agpo' => ['label'=>'AGPO Certificate (Youth / Women / PWD)','authority'=>'Treasury','regex'=>'/^(YOUTH|WOMEN|PWD)[-]?[A-Z0-9]{4,15}$/','format_field'=>'cert_level','required'=>false,'expiry'=>true,'hint'=>'AGPO cert for Youth, Women, or PWD.'],
            ],
        ],
    ];
}

function parse_date($s) {
    if (!$s) return null;
    foreach (['Y-m-d','d/m/Y','d M Y'] as $fmt) {
        $d = DateTime::createFromFormat($fmt, $s);
        if ($d) return $d;
    }
    return null;
}

function evaluate_cert($spec, $row) {
    $value = isset($row['cert_number']) ? trim($row['cert_number']) : '';
    if (!$row || !$value) return ['status'=>'missing','msg'=>'Not recorded','valid'=>false];
    $fmt_field = isset($spec['format_field']) ? $spec['format_field'] : 'cert_number';
    $fmt_val = ($fmt_field === 'cert_level' && isset($row['cert_level'])) ? trim($row['cert_level']) : $value;
    if (isset($spec['regex']) && $fmt_val && !preg_match($spec['regex'], $fmt_val)) {
        return ['status'=>'invalid','msg'=>'Format invalid for '.$spec['label'],'valid'=>false];
    }
    if (!empty($spec['expiry'])) {
        $exp = parse_date($row['expiry_date'] ?? '');
        if (!$exp) return ['status'=>'unknown','msg'=>'No expiry date recorded','valid'=>false];
        $today = new DateTime();
        if ($exp < $today) return ['status'=>'expired','msg'=>'Expired '.$exp->format('Y-m-d'),'valid'=>false];
        $diff = $today->diff($exp)->days;
        if ($diff <= 30) return ['status'=>'expiring','msg'=>'Expires '.$exp->format('Y-m-d').' (<=30d)','valid'=>true];
        return ['status'=>'valid','msg'=>'Valid to '.$exp->format('Y-m-d'),'valid'=>true];
    }
    return ['status'=>'valid','msg'=>'Recorded (no expiry)','valid'=>true];
}

function evaluate_supplier($id) {
    $db = db();
    $sup = $db->query("SELECT * FROM suppliers WHERE id=$id")->fetch();
    if (!$sup) return null;
    $cc = $sup['country_code'];
    $reg = registry()[$cc];
    $certs = $db->query("SELECT * FROM certificates WHERE supplier_id=$id")->fetchAll();
    $by_key = [];
    foreach ($certs as $c) $by_key[$c['cert_key']] = $c;
    $results = [];
    foreach ($reg['certs'] as $key => $spec) {
        $row = $by_key[$key] ?? null;
        $ev = evaluate_cert($spec, $row);
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

function seed_demo() {
    $db = db();
    $today = date('Y-m-d');
    $future = date('Y-m-d', strtotime('+1 year'));
    $expired = date('Y-m-d', strtotime('-1 year'));
    // supplier 1: ZA construction, ready
    $db->exec("INSERT OR REPLACE INTO suppliers (id,user_id,country_code,legal_name,registration_no,tax_no,sector,contact_email) VALUES (1,1,'ZA','Cape Tech Solutions (Pty) Ltd','CSD998877','9123456789','construction','ops@capetech.co.za')");
    $db->exec("DELETE FROM certificates WHERE supplier_id=1");
    foreach ([
        [1,'ZA','csd','CSD998877','','',$future],
        [1,'ZA','tax_clearance','9123456789','','',$future],
        [1,'ZA','bbbee','BBBEE12345','4','',$future],
        [1,'ZA','cidb','9GB','9GB','',$future],
    ] as $c) {
        $db->exec("INSERT INTO certificates (supplier_id,country_code,cert_key,cert_number,cert_level,issued_date,expiry_date) VALUES ({$c[0]},'{$c[1]}','{$c[2]}','{$c[3]}','{$c[4]}','{$c[5]}','{$c[6]}')");
    }
    // supplier 2: KE, ready (AGPO optional missing)
    $db->exec("INSERT OR REPLACE INTO suppliers (id,user_id,country_code,legal_name,registration_no,tax_no,sector,contact_email) VALUES (2,2,'KE','Nairobi Digital Ltd','CPR123456','A123456789B','ict','ceo@nairobidigital.co.ke')");
    $db->exec("DELETE FROM certificates WHERE supplier_id=2");
    foreach ([
        [2,'KE','kra_tcc','A123456789B','','',$future],
        [2,'KE','brs','CPR123456','','',''],
        [2,'KE','agpo','','','',''],
    ] as $c) {
        $db->exec("INSERT INTO certificates (supplier_id,country_code,cert_key,cert_number,cert_level,issued_date,expiry_date) VALUES ({$c[0]},'{$c[1]}','{$c[2]}','{$c[3]}','{$c[4]}','{$c[5]}','{$c[6]}')");
    }
    // supplier 3: ZA, expired tax
    $db->exec("INSERT OR REPLACE INTO suppliers (id,user_id,country_code,legal_name,registration_no,tax_no,sector,contact_email) VALUES (3,3,'ZA','Gauteng Logistics CC','CSD556677','9111222333','logistics','admin@glogs.co.za')");
    $db->exec("DELETE FROM certificates WHERE supplier_id=3");
    foreach ([
        [3,'ZA','csd','CSD556677','','',$future],
        [3,'ZA','tax_clearance','9111222333','','',$expired],
        [3,'ZA','bbbee','BBBEE998','5','',$future],
    ] as $c) {
        $db->exec("INSERT INTO certificates (supplier_id,country_code,cert_key,cert_number,cert_level,issued_date,expiry_date) VALUES ({$c[0]},'{$c[1]}','{$c[2]}','{$c[3]}','{$c[4]}','{$c[5]}','{$c[6]}')");
    }
}

ensure_compliance_tables();
if (isset($_GET['seed']) || isset($_POST['seed'])) seed_demo();

$all = db()->query("SELECT id FROM suppliers ORDER BY id")->fetchAll(PDO::FETCH_COLUMN);
$reports = array_map('evaluate_supplier', $all);
$flag = ['valid'=>'✅','expiring'=>'⚠️','expired'=>'❌','missing'=>'❌','invalid'=>'❌','unknown'=>'❓'];
?>
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moya — Compliance Engine (Test)</title>
<style>
:root{--maxw:1140px;--blue:#0d6efd;--green:#198754;--red:#dc3545;--bg:#f6f8fb;--card:#fff;--ink:#1a2233;--mut:#6c757d}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink)}
.wrap{max-width:var(--maxw);margin:0 auto;padding:24px 18px}
h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 18px}
.card{background:var(--card);border:1px solid #e6eaf0;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 1px 3px rgba(20,30,60,.05)}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:13px;font-weight:600}
.ready{background:#e7f6ec;color:var(--green)}.notready{background:#fdeaea;color:var(--red)}
.score{font-size:30px;font-weight:800;margin:6px 0}
table{width:100%;border-collapse:collapse;margin-top:8px;font-size:14px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #eef1f5}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
.req{color:var(--blue);font-weight:600}.opt{color:var(--mut)}
.gap{background:#fff5f5;border-left:3px solid var(--red);padding:6px 10px;margin:6px 0;border-radius:6px}
.cta{display:inline-block;background:var(--blue);color:#fff;text-decoration:none;padding:9px 16px;border-radius:8px;font-weight:600;margin-top:8px}
.hint{color:var(--mut);font-size:12px;margin-top:2px}
.note{background:#fffbe6;border:1px solid #ffe58f;border-radius:8px;padding:10px 12px;font-size:13px;margin:12px 0}
a.link{color:var(--blue)}
</style></head>
<body><div class="wrap">
<h1>Moya — Compliance Engine</h1>
<p class="sub">Supplier bid-readiness tracker · dynamic per-country rule sets (SA vs KE)</p>

<div class="note">
  Internal tracker model: no public government verification API exists for SARS / CSD / KRA / AGPO,
  so clients record their cert number + expiry and the engine validates format, tracks validity/expiry,
  and scores readiness. Switch a supplier's <code>country_code</code> to flip the entire rule set.
</div>
<p><a class="cta" href="?seed=1">↻ Reset / seed demo suppliers</a>
   &nbsp; <a class="link" href="moya.php">← Back to tender desk</a></p>

<?php if (empty($reports)): ?>
  <div class="card"><p>No suppliers. <a class="cta" href="?seed=1">Seed demo data</a></p></div>
<?php endif; ?>

<?php foreach ($reports as $r): if (!$r) continue; ?>
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <div>
        <strong style="font-size:17px"><?= htmlspecialchars($r['legal_name']) ?></strong>
        <span class="badge" style="background:#eef2ff;color:#3a3aff;margin-left:6px"><?= $r['country'] ?> / <?= $r['country_code'] ?></span>
        <div class="hint">Authority: <?= htmlspecialchars($r['authority']) ?></div>
      </div>
      <div style="text-align:right">
        <div class="score" style="color:<?= $r['ready']?'var(--green)':'var(--red)' ?>"><?= $r['score'] ?>%</div>
        <span class="badge <?= $r['ready']?'ready':'notready' ?>"><?= $r['ready']?'✅ READY TO BID':'⛔ NOT READY' ?></span>
      </div>
    </div>
    <table>
      <thead><tr><th>Status</th><th>Certification</th><th>Authority</th><th>Detail</th></tr></thead>
      <tbody>
      <?php foreach ($r['certs'] as $c): $cls = $c['required'] ? 'req' : 'opt';
        $tag = $c['required'] ? 'REQ' : 'opt';
        $cond = $c['conditional'] ? " <span class='hint'>[sector:{$c['conditional']}]</span>" : '';
      ?>
        <tr>
          <td><?= $flag[$c['status']] ?? '?' ?> <b><?= strtoupper($c['status']) ?></b></td>
          <td><span class="<?= $cls ?>"><?= $tag ?></span> <?= htmlspecialchars($c['label']) ?><?= $cond ?></td>
          <td class="hint"><?= htmlspecialchars($c['authority']) ?></td>
          <td><?= htmlspecialchars($c['msg']) ?></td>
        </tr>
      <?php endforeach; ?>
      </tbody>
    </table>
    <?php if ($r['gaps']): ?>
      <div style="margin-top:8px"><b>Gaps to close:</b>
      <?php foreach ($r['gaps'] as $g): ?>
        <div class="gap"><?= htmlspecialchars($g['label']) ?> — <?= htmlspecialchars($g['msg']) ?></div>
      <?php endforeach; ?>
      </div>
    <?php endif; ?>
    <div class="hint" style="margin-top:6px"><?= htmlspecialchars($r['certs'][0]['hint']) ?></div>
  </div>
<?php endforeach; ?>
</div></body></html>
