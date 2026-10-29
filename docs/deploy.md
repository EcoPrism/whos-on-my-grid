# Deploying Who's On My Grid

One container on Azure Container Apps serves the API and the built web app. Everything sits in
one resource group in the EcoPrism - Prod subscription (`infra/deploy.json` names it). The
hostname is the app's own `*.azurecontainerapps.io` until `whoisonmygrid.com` is wired through Cloudflare.

## What is in the group

| Resource | Why | Cost, roughly |
|---|---|---|
| Container App `ca-grid`, 0.5 vCPU / 1 GiB, one replica | API + web. One replica by design: the in-process in-flight registry and the cache's temp files assume one writer | $25 to $30 a month |
| Container Apps environment `cae-grid` (consumption) | Hosts the app, mounts the share | included |
| Storage account: file share `grid`, tables `users` and `usage` | `/mnt/grid/briefs` is the brief cache (shared links survive restarts), `/mnt/grid/scenarios` the what-if cache (same reason), `/mnt/grid/cards` the share-card cache, `/mnt/grid/ground` the downloaded datasets; the tables record sign-ins and generated brief ids | under $1 |
| Key Vault `kv-grid-*`, RBAC | `gateway-key`, `baseten-key`, `session-secret`, `c2pa-cert-chain`, `c2pa-private-key`; the app reads them through its managed identity | under $1 |
| Container Registry, Basic | The image | $5 |
| Log Analytics, capped at 1 GB/day | `EVT` lines from the app; never an address | pennies |

## Secrets and keys

- Secret values never pass through Bicep or the console. `scripts/deploy.ps1 -Phase secrets`
  copies `GRID_OPENAI_API_KEY` and `GRID_BASETEN_API_KEY` from `services/api/.env` into the vault
  through owner-only temp files, mints `session-secret` once (rotating it signs everyone out), and
  seeds the share with `data/ground`. Run that phase yourself.
- The share card's C2PA signing certificate and key go in the same way, from PEM files you name
  (see "C2PA content credentials" below). Without them the phase writes one space into
  `c2pa-cert-chain` and `c2pa-private-key`, which the app reads as "unsigned".
- The Google OAuth client id and the Maps key are public by design (the first is an audience, the
  second is HTTP-referrer restricted). The client id lives in `infra/deploy.json`; the Maps key is
  read from `web/.env` at image build time and passed as a secret build arg.

## First deploy

1. `az login` as a user who can create resource groups in the subscription.
2. Create the Google OAuth **Web application** client in Google Cloud project `ecoprism-ecoutil`
   (APIs & Services → Credentials). Consent screen: external, scopes `email` and `profile`.
   Authorized JavaScript origins: `http://localhost:5173` for now; the app's FQDN is added after
   step 6, and `https://whoisonmygrid.com` plus `https://www.whoisonmygrid.com` when the domain is
   live. No redirect URIs are needed (Google Identity Services uses a
   popup). Put the client id in `infra/deploy.json`. There is no `gcloud` command for a standard
   web client; it is created in the console (`gcloud iam oauth-clients` is Workforce Identity
   Federation, a different thing).
3. `./scripts/deploy.ps1 -Phase platform`
4. `./scripts/deploy.ps1 -Phase secrets` (yours to run: it reads `.env` files)
5. `./scripts/deploy.ps1 -Phase image`
6. `./scripts/deploy.ps1 -Phase app`. It prints the FQDN and polls `/api/health`.
7. Add `https://<fqdn>` to the OAuth client's JavaScript origins and to the Maps key's referrers
   (`gcloud services api-keys update`, key in project `ecoprism-ecoutil`).
8. Open the FQDN. Sign in, run one new address, open the brief link in a private window without
   signing in, run a test-set address from the dropdown without signing in.

A later release is `-Phase image` then `-Phase app` (or `-Phase all`, which re-runs the cheap
phases idempotently). A code change invalidates every cached brief by design (engine fingerprint),
so expect the first run of each address after a release to spend tokens.

## The gate

Opening a brief and running a test-set address (`eval/addresses.json`) need no sign-in. Making a
brief for a new address needs a Google sign-in and counts against `GRID_QUOTA_PER_USER_DAY` (5) and
`GRID_QUOTA_GLOBAL_DAY` (40), both set in `infra/deploy.json`. The `usage` table holds, per day,
the subject, email and brief id of each run; the `users` table holds email and first/last seen.
Never an address. The web page shows the remaining count and the rule in one line.

## Domain and Cloudflare

The domain is `whoisonmygrid.com`, on Cloudflare DNS. Azure's free managed certificate cannot be
issued or renewed behind Cloudflare's proxy (the docs name Cloudflare as a blocking intermediate
CNAME), so the proxy and a managed certificate are mutually exclusive:

- Proxy off (grey cloud): managed certificate, auto-renewed, no `cf-ipcountry` header, so the
  country gate stays off.
- Proxy on (orange cloud): a Cloudflare origin certificate (SSL/TLS, Origin Server, 15 years)
  uploaded to the environment, Cloudflare SSL mode Full (strict), and the country gate can go on.

1. Cloudflare DNS, proxy off to start: `A @` to the environment's static IP
   (`az containerapp env show --query properties.staticIp`), `CNAME www` to the app FQDN,
   `TXT asuid` and `TXT asuid.www` with the verification id
   (`az containerapp show --query properties.customDomainVerificationId`).
2. `az containerapp hostname add -n ca-grid -g rg-whoisinmygrid --hostname whoisonmygrid.com`, and
   again for `www.whoisonmygrid.com`.
3. Certificate. Managed: `az containerapp hostname bind ... --environment cae-grid
   --validation-method HTTP` for the apex and `CNAME` for `www`. Origin certificate: convert the
   PEM pair to PFX, `az containerapp env certificate upload -g rg-whoisinmygrid -n cae-grid
   --certificate-file grid.pfx`, then `hostname bind ... --certificate <name>` for each hostname,
   and turn the proxy on.
4. Set `"publicBaseUrl": "https://whoisonmygrid.com"` in `infra/deploy.json` and, with the proxy
   on only, `"allowedCountries": "US"`; run `-Phase app`. `publicBaseUrl` becomes
   `GRID_PUBLIC_BASE_URL`, the host share links, cards and Open Graph tags print; empty means the
   app FQDN. With the country gate on, the app reads `cf-ipcountry` and fails closed: the raw FQDN
   stops serving briefs, which is intended.
5. Add `https://whoisonmygrid.com` and `https://www.whoisonmygrid.com` to the Google OAuth client's
   origins, and `https://whoisonmygrid.com/*` and `https://*.whoisonmygrid.com/*` to the Maps key's
   referrers.

## C2PA content credentials

Every share card carries the AI disclosure in its pixels and an XMP packet with the IPTC digital
source type. With a certificate it also carries a signed C2PA manifest (`c2pa.created`,
`compositeWithTrainedAlgorithmicMedia`, generator "Who's on my grid", the model ids), which
LinkedIn and Content Credentials viewers show. The image always has `c2pa-python`; signing turns
on when both secrets hold PEM text.

What the app reads: `GRID_C2PA_CERT_PEM` (secret `c2pa-cert-chain`) and `GRID_C2PA_PRIVATE_KEY`
(secret `c2pa-private-key`). Locally, `GRID_C2PA_CERT_PATH` can name a chain file instead of
`GRID_C2PA_CERT_PEM`. `GRID_C2PA_TIMESTAMP_URL` defaults to DigiCert's free RFC 3161 service; when
it cannot be reached the card is signed without a timestamp, and an empty value never asks for one.

1. Get a certificate. Production wants a C2PA-conformant document-signing certificate from a CA on
   the C2PA trust list (the list and the conformance program are at c2pa.org); ask for ECDSA P-256
   (ES256). Requirements c2pa checks: the end-entity is not self-signed and not a CA,
   key usage `digitalSignature`, an extended key usage such as `emailProtection` or the C2PA
   document-signing OID, and a validity window that covers today.
   For a test, make your own CA and signer with openssl; it validates structurally but viewers show
   it as untrusted:

   ```
   openssl ecparam -name prime256v1 -genkey -noout -out ca.key
   openssl req -x509 -new -key ca.key -sha256 -days 365 -subj "/CN=Grid test CA/O=Grid" \
     -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
     -addext "keyUsage=critical,keyCertSign,cRLSign" -out ca.pem
   openssl ecparam -name prime256v1 -genkey -noout | openssl pkcs8 -topk8 -nocrypt -out key.pem
   openssl req -new -key key.pem -subj "/CN=Who's on my grid/O=Grid" -out signer.csr
   echo "basicConstraints=critical,CA:FALSE" > signer.ext
   echo "keyUsage=critical,digitalSignature" >> signer.ext
   echo "extendedKeyUsage=emailProtection" >> signer.ext
   openssl x509 -req -in signer.csr -CA ca.pem -CAkey ca.key -CAcreateserial -days 180 \
     -sha256 -extfile signer.ext -out signer.pem
   cat signer.pem ca.pem > chain.pem
   ```

   Keep these files outside the repo.
2. The chain file is PEM, end-entity first, then intermediates (the root may be left out). The key
   is unencrypted PKCS#8 (`-----BEGIN PRIVATE KEY-----`); convert an `EC PRIVATE KEY` with
   `openssl pkcs8 -topk8 -nocrypt -in old.key -out key.pem`. The script refuses anything else.
3. `./scripts/deploy.ps1 -Phase secrets -C2paCertChain <path>/chain.pem -C2paPrivateKey <path>/key.pem`
   (yours to run). It writes both secrets through owner-only temp files; nothing is printed.
4. `./scripts/deploy.ps1 -Phase app` rolls a revision that reads them. Container Apps reads Key
   Vault secrets when a revision starts, so a rotated certificate also needs this step.
5. Check: `curl -s https://<host>/api/card/<id>.png -o card.png` and open it at
   contentcredentials.org/verify, or `c2patool card.png`. The logs show `c2pa_skipped` (not
   configured) or `c2pa_failed` with the exception class only, never the key.

Cards are signed once and cached on the share, since a signature's timestamp makes every render
differ. The cache key includes a short hash of the public certificate, so loading or rotating one
renders the cards again. To turn signing off, write a blank into both secrets
(`az keyvault secret set --vault-name <vault> -n c2pa-private-key --value " "`, same for
`c2pa-cert-chain`) and run `-Phase app`.

An install that predates these secrets needs one `-Phase secrets` run (with or without the files)
before the next `-Phase app`; the app phase checks for every secret and says so.

## Operating

- Logs: `az containerapp logs show -n ca-grid -g rg-whoisinmygrid --follow`.
- Usage: `az storage entity query --table-name usage --account-name <account> --auth-mode login`.
- Briefs on the share: `az storage file list --share-name grid --path briefs --account-name <account>`.
- After the hackathon, rotate the Baseten key (it was pasted in chat) and re-run `-Phase secrets`
  then `-Phase app`.
