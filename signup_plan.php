<?php
/**
 * Moya — Plan Builder / Signup
 * Visitor selects:
 *   - base sector (their 1 FREE field)  [mandatory]
 *   - extra sectors (R500 each / month)
 * Live price is shown. On submit we RECORD the plan (base + extras + phone)
 * and create the account. Payment capture (PayFast) is intentionally back-burnered
 * — the plan is saved and the user gets straight into their dashboard.
 */

error_reporting(0);
require_once __DIR__ . '/moya.php';

$ALL_SECTORS = [
    'construction' => 'Construction', 'ict' => 'ICT & Technology', 'medical' => 'Medical & Healthcare',
    'security' => 'Security', 'logistics' => 'Logistics & Transport', 'education' => 'Education',
    'energy' => 'Energy & Electrical', 'agriculture' => 'Agriculture', 'consulting' => 'Consulting',
    'marketing' => 'Marketing', 'cleaning' => 'Cleaning & Hygiene', 'legal' => 'Legal & Financial',
    'property' => 'Property', 'mining' => 'Mining', 'manufacturing' => 'Manufacturing',
    'retail' => 'Retail', 'hospitality' => 'Hospitality', 'printing' => 'Printing & Signage',
    'hr' => 'HR & Recruitment', 'environmental' => 'Environmental', 'insurance' => 'Insurance',
    'telecoms' => 'Telecoms', 'aviation' => 'Aviation', 'maritime' => 'Maritime',
    'defence' => 'Defence', 'research' => 'Research', 'arts' => 'Arts & Culture',
    'sports' => 'Sports & Recreation', 'other' => 'Other',
];

$msg = '';
$created = false;
$tick = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
$selectedPlan = '';
$foundingInterest = '';

// Founding slot availability (scarcity). If full, the offer is hidden.
$foundingTaken = foundingSlotsTaken();
$foundingLeft = max(0, FOUNDING_SLOTS - $foundingTaken);
$showFounding = $foundingLeft > 0;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $name = trim($_POST['name'] ?? '');
    $surname = trim($_POST['surname'] ?? '');
    $email = trim(strtolower($_POST['email'] ?? ''));
    $phone = trim($_POST['phone'] ?? '');
    $password = $_POST['password'] ?? '';
    $base = trim($_POST['base_sector'] ?? '');
    $extras = array_filter(array_map('trim', $_POST['extra'] ?? []));
    $selectedPlan = trim($_POST['selected_plan'] ?? '');
    $consent = !empty($_POST['consent']);

    // Validate
    if (!$name || !$surname || !$email || !$phone || !$password) {
        $msg = 'Please complete all fields (name, surname, email, phone, password).';
    } elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $msg = 'Invalid email address.';
    } elseif (!$consent) {
        $msg = 'Please tick the consent box to agree to the Privacy Policy.';
    } elseif (strlen($password) < 8) {
        $msg = 'Password must be at least 8 characters.';
    } elseif (!$base) {
        $msg = 'Please choose your ONE free base sector — this is the field your tenders are scoped to.';
    } else {
        // Check existing
        $chk = db()->prepare("SELECT id FROM users WHERE email = ?");
        $chk->execute([$email]);
        if ($chk->fetch()) {
            $msg = 'That email is already registered. Please log in instead.';
        } else {
            $waPhone = '';
            $uid = registerUser($name, $email, $password, $base, $company ?? '', $waPhone, $extras, $consent);
            // Record the signed-up plan snapshot
            $plan = json_encode([
                'base' => $base,
                'extras' => array_values($extras),
                'monthly' => (count($extras) * EXTRA_SECTOR_FEE),
                'founding_interest' => $selectedPlan,
            ]);
            db()->prepare("UPDATE users SET plan = ?, moya_token = ? WHERE id = ?")
              ->execute([$plan, bin2hex(random_bytes(16)), $uid]);
            $created = true;
            $foundingInterest = in_array($selectedPlan, ['ict_pro', 'enterprise_ai'], true) ? $selectedPlan : '';
            // Auto-login
            $res = loginUser($email, $password);
            // Founding Pass selected? Email reservation + route to one-time PayFast checkout.
            if ($res['ok'] && $showFounding && in_array($selectedPlan, ['ict_pro', 'enterprise_ai'], true)) {
                sendFoundingSelectEmails($name, $email, $selectedPlan);
                header('Location: process_founding_plan.php?plan=' . urlencode($selectedPlan));
                exit;
            }
        }
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Moya — Choose Your Plan</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#08090a;--bg-2:#0f1011;--panel:#191a1b;--line:rgba(255,255,255,.08);--text:#f7f8f8;--muted:#8a8f98;--accent:#7170ff;--ok:#3ddc97;--warn:#f5b544}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:30px}
a{color:var(--accent)}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:1.7rem;font-weight:800;margin-bottom:4px}
.sub{color:var(--muted);margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;margin-bottom:20px}
.card h2{font-size:1.1rem;font-weight:700;margin-bottom:14px}
label{display:block;font-size:.85rem;color:var(--muted-2);margin:14px 0 6px}
input,select{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:11px 13px;color:var(--text);font-size:.92rem;font-family:inherit;outline:none}
input:focus,select:focus{border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.sector{display:flex;align-items:center;gap:9px;background:var(--bg-2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;cursor:pointer}
.sector input{width:16px;height:16px;accent-color:var(--accent)}
.sector.base{border-color:var(--ok);cursor:not-allowed;opacity:.85}
.sector .tag{margin-left:auto;font-size:.72rem;color:var(--ok)}
.note{color:var(--muted);font-size:.86rem;margin-bottom:8px}
.summary{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;margin-top:18px;padding-top:18px;border-top:1px solid var(--line)}
.total{font-size:1.5rem;font-weight:800}
.total small{font-size:.78rem;color:var(--muted);font-weight:400}
.btn{background:linear-gradient(135deg,#7170ff,#5e6ad2);color:#fff;font-weight:700;padding:12px 24px;border-radius:10px;border:none;cursor:pointer;font-size:.95rem}
.btn:hover{transform:translateY(-1px)}
.msg{background:rgba(255,107,107,.12);border:1px solid rgba(255,107,107,.3);color:#ff8e8e;padding:12px 14px;border-radius:10px;margin-bottom:16px;font-size:.9rem}
.ok{background:rgba(61,220,151,.12);border-color:rgba(61,220,151,.3);color:var(--ok)}
.toggle{text-align:center;margin-top:16px;color:var(--muted);font-size:.88rem}
.crumbs{margin-bottom:16px;font-size:.85rem;color:var(--muted)}
.wa{display:flex;align-items:center;gap:10px;background:rgba(61,220,151,.06);border:1px solid rgba(61,220,151,.25);border-radius:10px;padding:12px 14px;margin-top:10px}
.wa input{width:16px;height:16px;accent-color:var(--ok)}

/* Founding Lifetime Pass upsell */
.found-head{display:flex;align-items:center;gap:10px;margin-bottom:6px}
.found-badge{display:inline-flex;align-items:center;gap:6px;font-size:.7rem;font-weight:800;letter-spacing:.4px;text-transform:uppercase;color:#0b0c0e;background:linear-gradient(135deg,#f5b544,#ffd27a);padding:4px 10px;border-radius:999px}
.found-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.fplan{position:relative;background:var(--bg-2);border:1.5px solid var(--line);border-radius:14px;padding:18px;cursor:pointer;transition:border-color .2s,transform .15s}
.fplan:hover{transform:translateY(-2px)}
.fplan.sel{border-color:var(--accent);background:rgba(113,112,255,.07)}
.fplan .rec{position:absolute;top:-10px;right:14px;font-size:.64rem;font-weight:800;color:#0b0c0e;background:var(--ok);padding:3px 9px;border-radius:999px}
.fplan h3{font-size:1.02rem;font-weight:700;margin-bottom:4px}
.fprice{font-size:1.5rem;font-weight:800;margin:6px 0 2px;color:var(--text)}
.fprice small{font-size:.74rem;color:var(--muted);font-weight:400}
.fplan ul{list-style:none;margin:10px 0 0;padding:0;font-size:.82rem;color:var(--muted)}
.fplan li{display:flex;gap:8px;padding:3px 0;line-height:1.4}
.fplan li svg{width:15px;height:15px;flex:0 0 auto;color:var(--ok);margin-top:2px}
.fradio{position:absolute;opacity:0;pointer-events:none}
.skip{text-align:center;margin-top:14px;font-size:.84rem;color:var(--muted)}
.skip a{color:var(--accent);text-decoration:underline;cursor:pointer}
.found-note{background:rgba(245,181,68,.07);border:1px solid rgba(245,181,68,.25);border-radius:10px;padding:10px 14px;margin-top:12px;font-size:.8rem;color:var(--muted)}
@media(max-width:560px){.found-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <div class="crumbs"><a href="dashboard.php">← Moya</a></div>
  <h1>Build Your Moya Plan</h1>
  <div class="sub">Pick the field your FREE account is scoped to. It's included at no cost — we'll take you straight into your dashboard.</div>

  <?php if ($msg && !$created): ?><div class="msg"><?= htmlspecialchars($msg) ?></div><?php endif; ?>
  <?php if ($created): ?>
    <div class="msg ok">✅ Your Moya account is ready — your dashboard is scoped to your selected sectors. <?php if (!empty($res['ok'])): ?><a href="dashboard.php">Go to your dashboard →</a><?php endif; ?></div>
    <?php if ($foundingInterest): ?>
    <div class="msg ok" style="background:rgba(245,181,68,.1);border-color:rgba(245,181,68,.3);color:var(--warn)">⚡ Founding Pass selected (<?= $foundingInterest==='enterprise_ai'?'Enterprise AI &amp; Intelligence':'ICT Core Pro' ?>, R<?= $foundingInterest==='enterprise_ai'?'4,999':'2,499' ?> once-off). We've saved your interest and will email your secure payment link shortly.</div>
    <?php endif; ?>
  <?php endif; ?>

  <?php if (!$created): ?>
  <form method="POST">
    <div class="card">
      <h2>Your details</h2>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div><label>First name *</label><input name="name" required></div>
        <div><label>Surname *</label><input name="surname" required></div>
      </div>
      <label>Email *</label><input type="email" name="email" required>
      <label>Phone *</label><input name="phone" placeholder="+27 ..." required>
      <label>Password (8+ chars) *</label><input type="password" name="password" required>
    </div>

    <div class="card">
      <h2>1 · Your FREE base sector</h2>
      <p class="note">This is the ONE industry your free tenders are scoped to. Choose carefully — it's included at no cost.</p>
      <select name="base_sector" required>
        <option value="" disabled selected>Select your industry / field *</option>
        <?php foreach ($ALL_SECTORS as $k => $l): ?><option value="<?= $k ?>"><?= htmlspecialchars($l) ?></option><?php endforeach; ?>
      </select>
    </div>

    <?php if ($showFounding): ?>
    <div class="card">
      <div class="found-head">
        <span class="found-badge">⚡ Founding Cohort</span>
        <h2 style="margin:0">Lock lifetime access — pay once, never monthly</h2>
      </div>
      <p class="note">We're opening <b><?= FOUNDING_SLOTS ?> Founding Integrator slots</b> — <b style="color:var(--warn)"><?= $foundingLeft ?> remaining</b>. Upgrade once to a Lifetime Pass and permanently unlock every ICT / Pro AV / Hardware scope — no subscription, ever. Your free base sector stays yours either way.</p>
      <div class="found-grid">
        <label class="fplan" id="plan-ict_pro">
          <input class="fradio" type="radio" name="selected_plan" value="ict_pro">
          <span class="rec">Recommended</span>
          <h3>ICT Core Pro — Lifetime</h3>
          <div class="fprice">R 2,499 <small>once-off</small></div>
          <ul>
            <li><?= $tick ?> Permanent access to all 4 ICT sub-scopes (Pro AV, ITC, Hardware, Turnkey SI)</li>
            <li><?= $tick ?> Daily automated tender digests</li>
            <li><?= $tick ?> No monthly bills, ever</li>
          </ul>
        </label>
        <label class="fplan" id="plan-enterprise_ai">
          <input class="fradio" type="radio" name="selected_plan" value="enterprise_ai">
          <h3>Enterprise AI &amp; Intelligence — Lifetime</h3>
          <div class="fprice">R 4,999 <small>once-off</small></div>
          <ul>
            <li><?= $tick ?> Everything in ICT Core Pro</li>
            <li><?= $tick ?> AI &amp; Automation module + early private project tracking</li>
            <li><?= $tick ?> Automated PDF RFP / BOQ parsing engine</li>
          </ul>
        </label>
      </div>
      <div class="found-note">⚡ Founding price is a one-time payment. On "Create My Account" you'll be taken securely to PayFast to complete the one-time payment, then dropped into your unlocked dashboard.</div>
      <p class="skip">Just want the free account? <a onclick="document.querySelectorAll('input[name=selected_plan]').forEach(e=>e.checked=false);document.querySelectorAll('.fplan').forEach(e=>e.classList.remove('sel'));">Skip the Founding Pass →</a></p>
    </div>
    <?php endif; ?>

    <div class="card">
      <label style="display:flex;align-items:flex-start;gap:10px;font-size:.84rem;color:var(--muted);margin:6px 0 4px;cursor:pointer">
        <input type="checkbox" name="consent" value="1" required style="margin-top:4px;width:16px;height:16px;accent-color:var(--accent)">
        <span>I agree to the <a href="privacy.php" target="_blank" style="color:var(--accent)">Privacy Policy</a> and consent to MY-LO storing my company, tax and certification details for bid-readiness tracking. I understand no government body is queried automatically.</span>
      </label>
      <div class="summary">
        <div class="total">Free <small>base sector included</small></div>
        <button class="btn" type="submit">Create My Account</button>
      </div>
      <p class="note" style="margin-top:12px">Your base sector is included free — no payment required to get started. You'll go straight into your dashboard.</p>
    </div>

    <script>
      document.querySelectorAll('input[name=selected_plan]').forEach(function(r){
        r.addEventListener('change', function(){
          document.querySelectorAll('.fplan').forEach(function(p){p.classList.remove('sel');});
          if (r.checked) { document.getElementById('plan-'+r.value).classList.add('sel'); }
        });
      });
    </script>
  </form>
  <?php endif; ?>
</div>

</body>
</html>
