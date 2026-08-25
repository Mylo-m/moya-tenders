<?php
/**
 * Moya — My Compliance (logged-in client)
 * Lets a signed-in client manage their supplier profile + certificates for their
 * country (ZA or KE), see a live bid-readiness score, and (soon) generate a bid pack.
 * Country is driven by the user's country_code (set at signup / here).
 */

error_reporting(0);
define('DB_PATH', __DIR__ . '/moya.db');
require_once __DIR__ . '/moya.php';        // getCurrentUser(), db(), constants
require_once __DIR__ . '/compliance_lib.php';     // engine

$user = getCurrentUser();
if (!$user) { header('Location: dashboard.php'); exit; }

ensure_compliance_tables();

$db = db();
// sync user country_code if missing
if (empty($user['country_code'])) {
    $user['country_code'] = 'ZA';
    $db->prepare("UPDATE users SET country_code='ZA' WHERE id=?")->execute([$user['id']]);
}
$supplier = c_get_or_create_supplier($user['id'], $user['country_code']);

$msg = '';
// Save profile + certs
if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_POST['save_compliance'])) {
    $cc = $_POST['country_code'] ?? $supplier['country_code'];
    $legal = trim($_POST['legal_name'] ?? $supplier['legal_name']);
    $regno = trim($_POST['registration_no'] ?? '');
    $taxno = trim($_POST['tax_no'] ?? '');
    $sector = trim($_POST['sector'] ?? $supplier['sector']);
    $email = trim($_POST['contact_email'] ?? $supplier['contact_email']);
    // update supplier row
    $db->prepare("UPDATE suppliers SET country_code=?, legal_name=?, registration_no=?, tax_no=?, sector=?, contact_email=? WHERE id=?")
       ->execute([$cc, $legal, $regno, $taxno, $sector, $email, $supplier['id']]);
    // update user country_code + sector too (drives tender matching later)
    $db->prepare("UPDATE users SET country_code=?, sector=? WHERE id=?")->execute([$cc, $sector, $user['id']]);
    // upsert each cert
    $reg = compliance_registry()[$cc];
    foreach (array_keys($reg['certs']) as $key) {
        $num = trim($_POST['cert_'.$key] ?? '');
        $lvl = trim($_POST['lvl_'.$key] ?? '');
        $iss = trim($_POST['iss_'.$key] ?? '');
        $exp = trim($_POST['exp_'.$key] ?? '');
        $existing = $db->query("SELECT id FROM certificates WHERE supplier_id={$supplier['id']} AND cert_key='$key'")->fetch();
        if ($existing) {
            $db->prepare("UPDATE certificates SET cert_number=?, cert_level=?, issued_date=?, expiry_date=? WHERE id=?")
               ->execute([$num, $lvl, $iss, $exp, $existing['id']]);
        } else {
            $db->prepare("INSERT INTO certificates (supplier_id,country_code,cert_key,cert_number,cert_level,issued_date,expiry_date) VALUES (?,?,?,?,?,?,?)")
                ->execute([$supplier['id'], $cc, $key, $num, $lvl, $iss, $exp]);
        }
    }
    $msg = 'Your compliance profile was saved and re-evaluated.';
    // reload supplier + user
    $supplier = c_get_or_create_supplier($user['id'], $cc);
    $user = getCurrentUser(); // refresh
}

$cc = $supplier['country_code'];
$reg = compliance_registry()[$cc];
$report = c_evaluate_supplier($supplier['id']);

// current cert values
$certs = $db->query("SELECT * FROM certificates WHERE supplier_id={$supplier['id']}")->fetchAll();
$by_key = [];
foreach ($certs as $c) $by_key[$c['cert_key']] = $c;

$ALL_SECTORS = [
    'construction'=>'Construction','ict'=>'ICT & Technology','medical'=>'Medical & Healthcare',
    'security'=>'Security','logistics'=>'Logistics & Transport','education'=>'Education',
    'energy'=>'Energy & Electrical','agriculture'=>'Agriculture','consulting'=>'Consulting',
    'marketing'=>'Marketing','cleaning'=>'Cleaning & Hygiene','legal'=>'Legal & Financial',
    'property'=>'Property','mining'=>'Mining','manufacturing'=>'Manufacturing','retail'=>'Retail',
    'hospitality'=>'Hospitality','printing'=>'Printing & Signage','hr'=>'HR & Recruitment',
    'environmental'=>'Environmental','insurance'=>'Insurance','telecoms'=>'Telecoms',
    'aviation'=>'Aviation','maritime'=>'Maritime','defence'=>'Defence','research'=>'Research',
    'arts'=>'Arts & Culture','sports'=>'Sports & Recreation','other'=>'Other',
];
?>
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moya — My Compliance</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#08090a;--bg-2:#0f1011;--panel:#191a1b;--line:rgba(255,255,255,.08);--text:#f7f8f8;--muted:#8a8f98;--accent:#7170ff;--ok:#3ddc97;--warn:#f5b544;--danger:#ff6b6b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:30px}
a{color:var(--accent)}
.wrap{max-width:860px;margin:0 auto}
h1{font-size:1.6rem;font-weight:800;margin-bottom:4px}
.sub{color:var(--muted);margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px;margin-bottom:20px}
.card h2{font-size:1.05rem;font-weight:700;margin-bottom:14px}
.crumbs{margin-bottom:16px;font-size:.85rem;color:var(--muted)}
label{display:block;font-size:.82rem;color:var(--muted);margin:12px 0 5px}
input,select{width:100%;background:var(--bg-2);border:1px solid var(--line);color:var(--text);border-radius:9px;padding:10px 12px;font-size:.92rem;font-family:inherit}
input:focus,select:focus{outline:none;border-color:var(--accent)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.cert{border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px;background:var(--bg-2)}
.cert .top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
.cert .name{font-weight:700;font-size:.95rem}
.cert .req{font-size:.7rem;padding:2px 8px;border-radius:999px}
.req-y{background:rgba(113,112,255,.18);color:var(--accent)}
.req-o{background:rgba(138,143,152,.15);color:var(--muted)}
.status{font-size:.78rem;font-weight:700;padding:3px 9px;border-radius:999px}
.s-valid{background:rgba(61,220,151,.15);color:var(--ok)}
.s-expiring{background:rgba(245,181,68,.15);color:var(--warn)}
.s-expired,.s-missing,.s-invalid{background:rgba(255,107,107,.15);color:var(--danger)}
.s-unknown{background:rgba(138,143,152,.15);color:var(--muted)}
.hint{color:var(--muted);font-size:.78rem;margin-top:4px}
.btn{background:linear-gradient(135deg,#7170ff,#5e6ad2);color:#fff;font-weight:700;padding:11px 22px;border-radius:10px;border:none;cursor:pointer;font-size:.92rem}
.btn:hover{transform:translateY(-1px)}
.msg{background:rgba(61,220,151,.12);border:1px solid rgba(61,220,151,.3);color:var(--ok);padding:12px 14px;border-radius:10px;margin-bottom:16px;font-size:.9rem}
.scorebox{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.score{font-size:38px;font-weight:800}
.badge{display:inline-block;padding:5px 13px;border-radius:999px;font-weight:700;font-size:.9rem}
.b-ready{background:rgba(61,220,151,.18);color:var(--ok)}
.b-not{background:rgba(255,107,107,.18);color:var(--danger)}
.gap{background:rgba(255,107,107,.08);border-left:3px solid var(--danger);padding:7px 11px;margin:6px 0;border-radius:6px;font-size:.85rem}
.note{background:rgba(245,181,68,.1);border:1px solid rgba(245,181,68,.3);border-radius:8px;padding:10px 12px;font-size:.82rem;color:var(--warn);margin-bottom:14px}
</style></head>
<body><div class="wrap">
<div class="crumbs"><a href="dashboard.php">← Moya Dashboard</a> · <a href="account.php">My Sectors</a></div>
<h1>My Compliance</h1>
<div class="sub">Track the certifications your country's procurement rules require. Your readiness score updates as you fill in valid, unexpired certificates.</div>

<?php if ($msg): ?><div class="msg"><?= htmlspecialchars($msg) ?></div><?php endif; ?>
<div class="note">Internal tracker: there is no public government API to auto-verify SARS / CSD / KRA / AGPO, so you enter your certificate numbers and expiry dates and the engine validates format + expiry for you.</div>

<form method="POST" class="card">
  <h2>Supplier profile &amp; country</h2>
  <div class="row">
    <div><label>Country / hub</label>
      <select name="country_code" onchange="this.form.submit()">
        <option value="ZA" <?= $cc==='ZA'?'selected':'' ?>>South Africa</option>
        <option value="KE" <?= $cc==='KE'?'selected':'' ?>>Kenya</option>
      </select>
      <div class="hint">Switches the entire rule set (CSD/SARS/B-BBEE/CIDB ↔ KRA/BRS/AGPO).</div>
    </div>
    <div><label>Registered name</label>
      <input name="legal_name" value="<?= htmlspecialchars($supplier['legal_name']) ?>" required>
    </div>
  </div>
  <div class="row">
    <div><label>Registration / company No.</label>
      <input name="registration_no" value="<?= htmlspecialchars($supplier['registration_no']) ?>"></div>
    <div><label>Tax No. / PIN</label>
      <input name="tax_no" value="<?= htmlspecialchars($supplier['tax_no']) ?>"></div>
  </div>
  <div class="row">
    <div><label>Primary sector</label>
      <select name="sector">
        <?php foreach ($ALL_SECTORS as $k=>$l): ?><option value="<?= $k ?>" <?= $supplier['sector']===$k?'selected':'' ?>><?= $l ?></option><?php endforeach; ?>
      </select>
      <div class="hint">Drives CIDB requirement (construction only).</div>
    </div>
    <div><label>Contact email</label>
      <input name="contact_email" value="<?= htmlspecialchars($supplier['contact_email']) ?>"></div>
  </div>

  <h2 style="margin-top:20px">Certifications — <?= htmlspecialchars($reg['label']) ?></h2>
  <input type="hidden" name="save_compliance" value="1">
  <?php foreach ($reg['certs'] as $key=>$spec):
      $c = $by_key[$key] ?? null;
      $req_cls = !empty($spec['required']) ? 'req-y':'req-o';
      $req_txt = !empty($spec['required']) ? 'REQUIRED':'optional';
      $cur = $c ? c_status_flag($c['status']) . ' ' . strtoupper($c['status']) : '❓ NOT SET';
      $cur_cls = 's-'.($c['status'] ?? 'unknown');
      $cond = $spec['conditional'] ?? null;
  ?>
    <div class="cert">
      <div class="top">
        <span class="name"><?= htmlspecialchars($spec['label']) ?><?= $cond? ' <span class="hint">(construction bids only)</span>':'' ?></span>
        <span class="req <?= $req_cls ?>"><?= $req_txt ?></span>
      </div>
      <div class="top" style="margin-bottom:6px">
        <span class="hint">Authority: <?= htmlspecialchars($spec['authority']) ?></span>
        <span class="status <?= $cur_cls ?>"><?= $cur ?></span>
      </div>
      <div class="row">
        <div><label><?= $spec['format_field']==='cert_level' ? 'Certificate / level number' : 'Certificate number' ?></label>
          <input name="cert_<?= $key ?>" value="<?= htmlspecialchars($c['cert_number'] ?? '') ?>" placeholder="<?= $spec['format_field']==='cert_level' ? 'e.g. 9GB / 4' : 'e.g. '.( $cc==='KE'?'A123456789B':'9123456789') ?>"></div>
        <?php if ($spec['format_field']==='cert_level'): ?>
        <div><label>Level / grade</label>
          <input name="lvl_<?= $key ?>" value="<?= htmlspecialchars($c['cert_level'] ?? '') ?>" placeholder="e.g. 9GB / 4"></div>
        <?php endif; ?>
      </div>
      <?php if (!empty($spec['expiry'])): ?>
      <div class="row">
        <div><label>Issued date (YYYY-MM-DD)</label>
          <input name="iss_<?= $key ?>" value="<?= htmlspecialchars($c['issued_date'] ?? '') ?>"></div>
        <div><label>Expiry date (YYYY-MM-DD)</label>
          <input name="exp_<?= $key ?>" value="<?= htmlspecialchars($c['expiry_date'] ?? '') ?>"></div>
      </div>
      <?php endif; ?>
      <div class="hint"><?= htmlspecialchars($spec['hint']) ?></div>
    </div>
  <?php endforeach; ?>
  <button class="btn" type="submit">Save &amp; re-evaluate</button>
</form>

<div class="card">
  <h2>Bid-readiness report</h2>
  <div class="scorebox">
    <div class="score" style="color:<?= $report['ready']?'var(--ok)':'var(--danger)' ?>"><?= $report['score'] ?>%</div>
    <span class="badge <?= $report['ready']?'b-ready':'b-not' ?>"><?= $report['ready']?'✅ READY TO BID':'⛔ NOT READY' ?></span>
    <span class="hint"><?= htmlspecialchars($report['authority']) ?></span>
  </div>
  <?php if ($report['gaps']): ?>
    <div style="margin-top:14px"><b>Close these gaps:</b>
    <?php foreach ($report['gaps'] as $g): ?><div class="gap"><?= c_status_flag($g['status']) ?> <?= htmlspecialchars($g['label']) ?> — <?= htmlspecialchars($g['msg']) ?></div><?php endforeach; ?>
    </div>
  <?php else: ?>
    <p class="hint" style="margin-top:12px">All required certifications recorded, valid and unexpired.</p>
  <?php endif; ?>
  <p style="margin-top:14px"><a class="btn" href="doc_engine.php?supplier=<?= $supplier['id'] ?>" style="text-decoration:none">Generate bid pack →</a></p>
</div>
</div></body></html>
