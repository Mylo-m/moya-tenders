<?php
/**
 * Moya — My Sectors (Account & Upsell)
 * Shows the user's free base sector and lets them add extra sectors
 * at R500 / sector / month. Selection is saved immediately; the PayFast
 * checkout step is wired where indicated.
 */

error_reporting(0);
require_once __DIR__ . '/moya.php';

$user = getCurrentUser();
if (!$user) {
    header('Location: dashboard.php');
    exit;
}

// GDPR/POPIA data deletion (self-service)
if (isset($_GET['action']) && $_GET['action'] === 'delete' && isset($_GET['confirm']) && $_GET['confirm'] === 'yes') {
    $db = db();
    $uid = $user['id'];
    // remove linked compliance data + sessions, then the user
    $db->prepare("DELETE FROM certificates WHERE supplier_id IN (SELECT id FROM suppliers WHERE user_id=?)")->execute([$uid]);
    $db->prepare("DELETE FROM suppliers WHERE user_id=?")->execute([$uid]);
    $db->prepare("DELETE FROM sessions WHERE user_id=?")->execute([$uid]);
    $db->prepare("DELETE FROM users WHERE id=?")->execute([$uid]);
    setcookie('tm_token', '', time() - 3600, '/', '', true, true);
    header('Location: privacy.php?deleted=1');
    exit;
}

// All sectors we track (must match the scraper's SECTOR_KEYWORDS keys)
$ALL_SECTORS = [
    'construction' => 'Construction',
    'ict' => 'ICT & Technology',
    'medical' => 'Medical & Healthcare',
    'security' => 'Security',
    'logistics' => 'Logistics & Transport',
    'education' => 'Education',
    'energy' => 'Energy & Electrical',
    'agriculture' => 'Agriculture',
    'consulting' => 'Consulting',
    'marketing' => 'Marketing',
    'cleaning' => 'Cleaning & Hygiene',
    'legal' => 'Legal & Financial',
    'property' => 'Property',
    'mining' => 'Mining',
    'manufacturing' => 'Manufacturing',
    'retail' => 'Retail',
    'hospitality' => 'Hospitality',
    'printing' => 'Printing & Signage',
    'hr' => 'HR & Recruitment',
    'environmental' => 'Environmental',
    'insurance' => 'Insurance',
    'telecoms' => 'Telecoms',
    'aviation' => 'Aviation',
    'maritime' => 'Maritime',
    'defence' => 'Defence',
    'research' => 'Research',
    'arts' => 'Arts & Culture',
    'sports' => 'Sports & Recreation',
    'other' => 'Other',
];

$base = $user['base_sector'] ?? '';
$extra = array_filter(array_map('trim', explode(',', $user['extra_sectors'] ?? '')));
$fee = (int)($user['monthly_extra_fee'] ?? 0);
$ai = !empty($user['ai_module']);
$aiFee = $ai ? AI_MODULE_FEE : 0;

$message = '';
// Handle save of extra-sector selection + AI module toggle
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $picked = $_POST['extra'] ?? [];
    $picked = array_filter(array_map('trim', $picked));
    // Never allow the base sector to be in the paid list.
    $picked = array_values(array_diff($picked, [$base]));
    $newFee = count($picked) * EXTRA_SECTOR_FEE;
    $aiOn = !empty($_POST['ai_module']) ? 1 : 0;
    $db = db();
    $db->prepare("UPDATE users SET extra_sectors = ?, monthly_extra_fee = ?, ai_module = ? WHERE id = ?")
       ->execute([implode(',', $picked), $newFee, $aiOn, $user['id']]);
    $extra = $picked;
    $fee = $newFee;
    $ai = (bool)$aiOn;
    $aiFee = $ai ? AI_MODULE_FEE : 0;
    $total = $newFee + $aiFee;
    $message = $total > 0
        ? 'Your plan was saved (R' . number_format($total, 0) . ' / month). Click "Pay via PayFast" below to activate paid access.'
        : 'Your plan was updated. No paid add-ons selected.';
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Moya — My Sectors</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#08090a;--bg-2:#0f1011;--panel:#191a1b;--line:rgba(255,255,255,.08);--text:#f7f8f8;--muted:#8a8f98;--accent:#7170ff;--ok:#3ddc97;--warn:#f5b544;--danger:#ff6b6b}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:30px}
a{color:var(--accent)}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:1.6rem;font-weight:800;margin-bottom:4px}
.sub{color:var(--muted);margin-bottom:24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:20px}
.card h2{font-size:1.1rem;font-weight:700;margin-bottom:14px}
.badge{display:inline-block;padding:5px 12px;border-radius:999px;font-size:.8rem;font-weight:600;background:rgba(61,220,151,.15);color:var(--ok);margin:4px 6px 4px 0}
.note{color:var(--muted);font-size:.9rem;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
.sector{display:flex;align-items:center;gap:10px;background:var(--bg-2);border:1px solid var(--line);border-radius:10px;padding:11px 13px;cursor:pointer;transition:border-color .15s}
.sector:hover{border-color:var(--accent)}
.sector input{accent-color:var(--accent);width:16px;height:16px}
.sector.base{opacity:.6;cursor:not-allowed}
.sector .tag{margin-left:auto;font-size:.72rem;color:var(--ok)}
.summary{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;margin-top:18px;padding-top:18px;border-top:1px solid var(--line)}
.total{font-size:1.4rem;font-weight:800}
.total small{font-size:.8rem;color:var(--muted);font-weight:400}
.btn{background:linear-gradient(135deg,#7170ff,#5e6ad2);color:#fff;font-weight:700;padding:11px 22px;border-radius:10px;border:none;cursor:pointer;font-size:.92rem}
.btn:hover{transform:translateY(-1px)}
.btn:disabled{opacity:.6;cursor:wait}
.btn.ok{background:linear-gradient(135deg,#1f9d6b,#3ddc97);color:#04210f}
.msg{background:rgba(61,220,151,.12);border:1px solid rgba(61,220,151,.3);color:var(--ok);padding:12px 14px;border-radius:10px;margin-bottom:16px;font-size:.9rem}
.crumbs{margin-bottom:18px;font-size:.85rem;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap">
  <div class="crumbs"><a href="dashboard.php">← Moya Dashboard</a></div>
  <h1>My Sectors</h1>
  <div class="sub">Your free account is scoped to one industry. Add more to widen your tender feed.</div>

  <?php if ($message): ?><div class="msg"><?= htmlspecialchars($message) ?></div><?php endif; ?>

  <div class="card">
    <h2>Your free base sector</h2>
    <div>
      <span class="badge"><?= htmlspecialchars($ALL_SECTORS[$base] ?? $base ?: 'Not set') ?></span>
      <span style="color:var(--muted);font-size:.85rem">Included free with your account.</span>
    </div>
  </div>

  <form method="POST" class="card">
    <h2>Add extra sectors — R500 / sector / month</h2>
    <p class="note">Tick the industries you want tenders for. Each extra sector is R500 per month on top of your base plan. Your base sector is free and cannot be removed.</p>
    <div class="grid">
      <?php foreach ($ALL_SECTORS as $key => $label): ?>
        <?php if ($key === $base) continue; ?>
        <label class="sector">
          <input type="checkbox" name="extra[]" value="<?= $key ?>" <?= in_array($key, $extra, true) ? 'checked' : '' ?>>
          <span><?= htmlspecialchars($label) ?></span>
          <?php if (in_array($key, $extra, true)): ?><span class="tag">+R500/mo</span><?php endif; ?>
        </label>
      <?php endforeach; ?>
    </div>
    <div class="summary">
      <label class="wa" style="display:flex;align-items:center;gap:10px;background:rgba(113,112,255,.06);border:1px solid rgba(113,112,255,.25);border-radius:10px;padding:12px 14px;margin-bottom:0">
        <input type="checkbox" name="ai_module" value="1" <?= $ai ? 'checked' : '' ?>>
        <span><strong>AI &amp; Intelligence module</strong> — automation, private project tracking &amp; document parsing — <strong>R<?= AI_MODULE_FEE ?>/month</strong></span>
      </label>
      <div class="total">Add-ons: R<?= number_format($fee + $aiFee, 0) ?> <small>/ month</small></div>
      <button class="btn" type="submit">Save Plan</button>
    </div>
  </form>

  <div class="card">
    <h2>Checkout &amp; payment status</h2>
    <?php
      $status = $user['payment_status'] ?? 'free';
      $paidUntil = $user['paid_until'] ?? '';
      $isPaid = ($status === 'active' && $paidUntil && strtotime($paidUntil) > time());
      $grand = $fee + $aiFee;
    ?>
    <p class="note">Monthly add-ons total: <strong>R<?= number_format($grand, 0) ?> / month</strong>.</p>
    <?php if ($isPaid): ?>
      <div class="msg ok">✅ Paid access active until <?= date('j M Y', strtotime($paidUntil)) ?>. Your extra sectors &amp; AI module are live.</div>
    <?php elseif ($grand > 0): ?>
      <div class="msg" style="background:rgba(245,181,68,.12);border-color:rgba(245,181,68,.3);color:var(--warn)">⏳ Selections saved but not yet active. Pay below to unlock extra sectors &amp; the AI module.</div>
    <?php else: ?>
      <div class="msg">No paid add-ons selected — your free base sector is active.</div>
    <?php endif; ?>
    <?php if ($grand > 0): ?>
      <a class="btn ok" href="pay_extra_sectors.php">Pay via PayFast</a>
    <?php else: ?>
      <span style="color:var(--muted)">Nothing to pay — add an add-on above to get started.</span>
    <?php endif; ?>
  </div>

  <div class="card">
    <h2>Data &amp; privacy</h2>
    <p class="note">Your company, tax and certification details are stored for bid-readiness tracking only. You can review our <a href="privacy.php">Privacy Policy</a>.</p>
    <a class="btn" style="background:linear-gradient(135deg,#ff6b6b,#d65b5b)" href="account.php?action=delete&confirm=yes" onclick="return confirm('Permanently delete your account and all linked compliance data? This cannot be undone.')">Delete my data</a>
  </div>
</div>
</body>
</html>
