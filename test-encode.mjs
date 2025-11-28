// Test the encoding in a Node.js environment
const domain = 'nvidia.wd5.myworkdayjobs.com';

// Simulate what our code does
const base64 = Buffer.from(domain, 'utf-8').toString('base64');
const base64url = base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');

console.log('Domain:', domain);
console.log('Base64:', base64);
console.log('Base64url:', base64url);

// Build URL
const apiBase = '/api/workday';
const tenantSlug = 'nvidia';
const careerSiteSlug = 'NVIDIAExternalCareerSite';
const jobsUrl = `${apiBase}/${base64url}/wday/cxs/${tenantSlug}/${careerSiteSlug}/jobs`;

console.log('Full URL:', jobsUrl);
console.log('Expected in error:', jobsUrl);
