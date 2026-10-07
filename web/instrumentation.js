// No external tag executes. GTM-compatible event objects stay in this page.
window.dataLayer = window.dataLayer || [];
let consent = {analytics: false, ads: false};
const brand = new URLSearchParams(location.search).get('brand') === 'harbour' ? 'harbour' : 'cedar';
const brandName = brand === 'harbour' ? 'Harbour Solutions' : 'Cedar Systems';
document.querySelector('#brand-label').textContent = `${brandName} / enterprise workflow solutions`;
document.title = `${brandName} · Enterprise workflow solutions`;
const storageKey = `signals:${brand}`;
let context = null;
function startContext() {
  const old = sessionStorage.getItem(storageKey);
  const query = new URLSearchParams(location.search);
  context = old ? JSON.parse(old) : {
    session: crypto.randomUUID(), campaign: query.get('utm_campaign') || '',
    source: query.get('utm_source') || '', medium: query.get('utm_medium') || '',
    gclid: consent.ads ? (query.get('gclid') || '') : ''
  };
  if (!consent.ads) context.gclid = '';
  sessionStorage.setItem(storageKey, JSON.stringify(context));
}
export function setConsent(analytics, ads) {
  consent = {analytics, ads};
  if (!analytics) {
    sessionStorage.removeItem(storageKey);
    context = null;
  } else startContext();
  if (!ads && context) {
    context.gclid = '';
    sessionStorage.setItem(storageKey, JSON.stringify(context));
  }
}
export async function track(action) {
  if (!consent.analytics) return {suppressed: true};
  const event = {
    schema_version: 2, event_id: crypto.randomUUID(), brand, kind: 'web',
    occurred_at: new Date().toISOString(),
    data: {...context, action, analytics_consent: true, ads_consent: consent.ads}
  };
  // Campaign dimensions only: click/session IDs stay out of the tag-facing data layer.
  window.dataLayer.push({event: action === 'contact_sales' ? 'generate_lead' : action,
    brand, campaign: context.campaign, source: context.source, medium: context.medium});
  let response;
  // Same immutable envelope on retry; never mint another ID for a lost acknowledgement.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      response = await fetch('/collect', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(event)});
      if (response.ok || response.status < 500) break;
    } catch (error) { if (attempt === 1) throw error; }
  }
  if (!response?.ok) throw new Error(`Collection failed: ${response?.status}`);
  return {...await response.json(), session: context.session};
}
window.signalDemo = {setConsent, track};
document.querySelector('#consent').addEventListener('click', async () => {
  setConsent(true, document.querySelector('#ads').checked);
  const receipt = await track('page_view');
  document.querySelector('#receipt').textContent = `Session ${receipt.session} · source retained for this tab`;
});
document.querySelector('#pricing').addEventListener('click', async () => {
  const receipt = await track('pricing_view');
  document.querySelector('#receipt').textContent = receipt.suppressed ? 'Analytics consent is required.' : 'Pricing interest recorded.';
});
document.querySelector('#sales-contact').addEventListener('submit', async event => {
  event.preventDefault();
  const receipt = await track('contact_sales');
  document.querySelector('#receipt').textContent = receipt.suppressed ? 'Analytics consent is required.' :
    `Sales inquiry received · session ${receipt.session} · awaiting verified CRM association`;
});
document.querySelector('#revoke').addEventListener('click', () => {
  setConsent(false, false);
  document.querySelector('#receipt').textContent = 'Browser tracking stopped and stored identifiers cleared.';
});
