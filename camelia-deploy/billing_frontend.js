// ═══════════════════════════════════════════
// PASTE THIS CODE IN YOUR index.html <script> section
// ═══════════════════════════════════════════

// ── 1. REPLACE the adminNav() function with this one: ──

function adminNav() {
  return `<div class="nav-tabs">
    <button class="nav-tab ${adminPage==="dashboard"?"active":""}" onclick="setAdminPage('dashboard')">Tableau de bord</button>
    <button class="nav-tab ${adminPage==="employees"?"active":""}" onclick="setAdminPage('employees')">Employés</button>
    <button class="nav-tab ${adminPage==="billing"?"active":""}" onclick="setAdminPage('billing')">Abonnement</button>
  </div>`;
}

// ── 2. In the render() function, ADD this condition: ──
// After: else if (adminPage === "employees") await renderAdminEmployees(el);
// Add:  else if (adminPage === "billing") await renderAdminBilling(el);

// ── 3. ADD these new functions: ──

async function renderAdminBilling(el) {
  let status;
  try {
    status = await api("/api/stripe/status");
  } catch(e) {
    status = {plan:"starter",maxEmployees:10,currentEmployees:1,subscriptionStatus:null,hasStripe:false};
  }

  const planNames = {starter:"Starter",pro:"Pro",enterprise:"Enterprise"};
  const planColors = {starter:"var(--muted)",pro:"var(--primary)",enterprise:"var(--success)"};
  const planPrices = {starter:"19€",pro:"49€",enterprise:"Sur mesure"};
  const statusLabels = {active:"Actif",trialing:"Essai gratuit",past_due:"Paiement en retard",canceled:"Annulé",unpaid:"Impayé"};
  const statusColors = {active:"var(--success)",trialing:"var(--blue)",past_due:"var(--warning)",canceled:"var(--danger)",unpaid:"var(--danger)"};

  const currentPlan = status.plan || 'starter';
  const subStatus = status.subscriptionStatus;
  const periodEnd = status.currentPeriodEnd ? new Date(status.currentPeriodEnd * 1000).toLocaleDateString('fr-FR',{day:'numeric',month:'long',year:'numeric'}) : null;

  el.innerHTML = `<div class="fade-up">
    ${adminNav()}
    <h2 class="page-title" style="margin-bottom:24px">Abonnement & Facturation</h2>

    <!-- Current plan -->
    <div class="card" style="margin-bottom:24px">
      <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">
        <div>
          <div style="font-size:13px;color:var(--muted);margin-bottom:4px">Plan actuel</div>
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:28px;font-weight:700;font-family:var(--font-display)">${planNames[currentPlan]}</span>
            ${subStatus ? `<span style="font-size:12px;font-weight:600;padding:3px 10px;border-radius:6px;background:${statusColors[subStatus]||'var(--muted)'}22;color:${statusColors[subStatus]||'var(--muted)'}">${statusLabels[subStatus]||subStatus}</span>` : '<span style="font-size:12px;font-weight:600;padding:3px 10px;border-radius:6px;background:var(--warning-light);color:var(--warning)">Non abonné</span>'}
          </div>
          ${periodEnd ? `<div style="font-size:13px;color:var(--muted);margin-top:6px">Prochain renouvellement : ${periodEnd}</div>` : ''}
        </div>
        <div style="text-align:right">
          <div style="font-size:13px;color:var(--muted)">Employés</div>
          <div style="font-size:22px;font-weight:700;font-family:var(--font-display)">${status.currentEmployees} <span style="font-size:14px;font-weight:400;color:var(--muted)">/ ${status.maxEmployees}</span></div>
        </div>
      </div>
      ${status.hasStripe ? `<div style="margin-top:16px"><button class="btn btn-outline btn-sm" onclick="openBillingPortal()">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><path d="M1 10h22"/></svg>
        Gérer la facturation</button></div>` : ''}
    </div>

    <!-- Plans comparison -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px">
      ${renderPlanCard('starter','Starter','19€','/ mois',[
        'Jusqu\\'à 10 employés','1 administrateur','Badgeage photo','Historique 30 jours','Support email'
      ], currentPlan === 'starter', currentPlan)}

      ${renderPlanCard('pro','Pro','49€','/ mois',[
        'Jusqu\\'à 100 employés','5 administrateurs','Badgeage photo','Historique illimité','Export Excel & PDF','Analytics avancés','Support prioritaire'
      ], currentPlan === 'pro', currentPlan, true)}

      ${renderPlanCard('enterprise','Enterprise','Sur mesure','',[
        'Employés illimités','Admins illimités','Tout le plan Pro','Multi-sites','API & intégrations','Account manager dédié','SLA 99.9%'
      ], currentPlan === 'enterprise', currentPlan)}
    </div>
  </div>`;
}

function renderPlanCard(planId, name, price, suffix, features, isCurrent, currentPlan, featured) {
  const checkSvg = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--success)" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>';

  let btnHtml = '';
  if (isCurrent) {
    btnHtml = '<button class="btn btn-outline btn-sm btn-block" disabled>Plan actuel</button>';
  } else if (planId === 'enterprise') {
    btnHtml = '<a href="mailto:contact@camelia.app" class="btn btn-outline btn-sm btn-block">Nous contacter</a>';
  } else {
    const isUpgrade = (currentPlan === 'starter' && planId === 'pro');
    const label = isUpgrade ? 'Passer au Pro' : 'Choisir ce plan';
    btnHtml = `<button class="btn ${featured?'btn-primary':'btn-outline'} btn-sm btn-block" onclick="startCheckout('${planId}')">${label}</button>`;
  }

  return `<div class="card" style="padding:28px;${featured?'border-color:var(--primary);box-shadow:0 8px 30px var(--primary-light)':''}${isCurrent?';border-color:var(--success)':''}">
    ${featured?'<div style="font-size:10px;font-weight:700;color:var(--primary);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Populaire</div>':''}
    ${isCurrent?'<div style="font-size:10px;font-weight:700;color:var(--success);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Actuel</div>':''}
    <div style="font-size:14px;font-weight:600;color:var(--muted);margin-bottom:4px">${name}</div>
    <div style="font-family:var(--font-display);font-size:32px;font-weight:700;margin-bottom:4px">${price} <span style="font-size:14px;font-weight:400;color:var(--muted)">${suffix}</span></div>
    <div style="height:1px;background:var(--border);margin:16px 0"></div>
    <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:20px;min-height:200px">
      ${features.map(f => `<div style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-secondary)">${checkSvg} ${f}</div>`).join('')}
    </div>
    ${btnHtml}
  </div>`;
}

async function startCheckout(plan) {
  try {
    const res = await api('/api/stripe/checkout', {method:'POST', body:{plan}});
    if (res.url) window.location.href = res.url;
  } catch(e) {
    toast(e.message, 'error');
  }
}

async function openBillingPortal() {
  try {
    const res = await api('/api/stripe/portal', {method:'POST'});
    if (res.url) window.location.href = res.url;
  } catch(e) {
    toast(e.message, 'error');
  }
}
