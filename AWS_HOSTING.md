# Host the resume on AWS

This guide deploys the JSON Resume site to `cv.danielteycheney.com` with Pulumi and Python.

## Architecture

- Route 53 resolves `cv.danielteycheney.com` to CloudFront.
- ACM issues the certificate in `us-east-1`, which is required for CloudFront.
- CloudFront uses an Origin Access Control (OAC) to read a private S3 bucket.
- The S3 bucket has public access blocked and an IAM bucket policy allowing only this CloudFront distribution to read objects.
- Pulumi uses the AWS credentials of the person or CI role running the deployment. AWS does not require a separate runtime IAM role for static S3/CloudFront hosting.

## Prerequisites

1. The registered domain is hosted in Route 53, or its authoritative name servers point to the Route 53 hosted zone returned by `aws route53 list-hosted-zones-by-name`.
2. Install AWS CLI, Pulumi CLI, `uv`, and Node.js/npm. `uv` can install the Python version required by this project.
3. Configure credentials with an IAM user or, preferably, an IAM role obtained through AWS SSO or GitHub Actions OIDC:

   ```sh
   aws configure sso
   aws sts get-caller-identity
   ```

   The deployment identity needs permission to manage ACM certificates, Route 53 records, CloudFront distributions and OACs, S3 buckets/objects/policies, and the relevant IAM policy documents. For production, scope those permissions to this stack and use a short-lived role rather than long-lived access keys.

## Local deployment role

The template at `infra/deploy-role.yaml` creates a dedicated `public-resume-deployer` role. It scopes S3 access to the configured site bucket, Route 53 record changes to the hosted zone, and ACM certificate operations to `us-east-1`. CloudFront create/list operations require wildcard resources; other CloudFront operations are scoped to this account's distributions and Origin Access Controls.

Create the role using credentials allowed to create IAM roles and policies. Your current IAM user can be the trusted principal:

```sh
aws cloudformation deploy \
   --template-file infra/deploy-role.yaml \\
   --stack-name public-resume-deployer \\
   --capabilities CAPABILITY_NAMED_IAM \\
   --parameter-overrides \\
      TrustedPrincipalArn=arn:aws:iam::032719885686:user/dfjt1985 \\
      BucketName=YOUR_GLOBALLY_UNIQUE_SITE_BUCKET \\
      HostedZoneId=Z28T3HGN0GB1AY \\
   --region ap-southeast-2
```

Replace the bucket name with the exact `bucketName` configured in `Pulumi.prod.yaml`. This uses your default AWS CLI profile to create the role; that user must have CloudFormation and IAM role creation permissions.

The IAM user also needs permission to call `sts:AssumeRole` on the new role. Add this inline policy to the user (or have an administrator grant the equivalent permission):

```json
{
   "Version": "2012-10-17",
   "Statement": [
      {
         "Effect": "Allow",
         "Action": "sts:AssumeRole",
         "Resource": "arn:aws:iam::032719885686:role/public-resume-deployer"
      }
   ]
}
```

To use the role locally, add a profile to `~/.aws/config`:

```ini
[profile resume-deploy]
role_arn = arn:aws:iam::032719885686:role/public-resume-deployer
source_profile = default
region = ap-southeast-2
```

Verify the assumed role before running Pulumi:

```sh
AWS_PROFILE=resume-deploy aws sts get-caller-identity
```

The returned ARN should contain `assumed-role/public-resume-deployer`. Set `export AWS_PROFILE=resume-deploy` in the shell where you run Pulumi. The identity used to create the role needs separate IAM/CloudFormation permissions; the deploy role intentionally does not grant IAM role creation or `iam:PassRole`.

## GitHub Actions OIDC

OIDC is not required for local deployment. AWS SSO or another authenticated AWS role is sufficient when running Pulumi from your workstation.

OIDC is recommended when deployment runs from GitHub Actions because it avoids storing long-lived AWS access keys in GitHub secrets. Create these separately as bootstrap resources:

- An AWS IAM OIDC provider for `token.actions.githubusercontent.com`.
- A restricted IAM deployment role trusted only by this repository and the intended branch or environment.
- A GitHub Actions workflow that assumes the role through OIDC.
- A `PULUMI_ACCESS_TOKEN` repository or environment secret, unless using another Pulumi backend.

The current stack does not create the OIDC provider or deployment role. Keep AWS trust conditions and permissions limited to this repository, and do not commit AWS access keys.

## Build the JSON Resume site

From the repository root, install the existing theme and export HTML into the directory consumed by Pulumi:

```sh
npm install
mkdir -p site
npx resume export site/index.html --format html --theme stackoverflow
PUPPETEER_EXECUTABLE_PATH="$(node -e 'process.stdout.write(require("puppeteer").executablePath())')" \
   npx resume export site/resume.pdf --format pdf --theme stackoverflow
cp resume.json site/resume.json
```

The site will serve the PDF at `/resume.pdf` and the source JSON at `/resume.json`. The explicit Puppeteer path makes the PDF export use the browser installed for this project, which avoids resume-cli's stale bundled Chromium on some Macs. Copy any images referenced by the generated site into `site/` as needed. Pulumi uploads every file below that directory and assigns common content types.

## Deploy with Pulumi

```sh
cd infra
uv python install 3.11
uv sync

pulumi login
pulumi stack init prod
```

Edit `Pulumi.prod.yaml` and set the stack-specific values. The `Pulumi.yaml` project schema documents the project inputs and supplies defaults for the root domain, subdomain, and site directory. The AWS provider region is configured per stack in `Pulumi.prod.yaml`.

```yaml
config:
   aws:region: ap-southeast-2
   public-resume:rootDomain: danielteycheney.com
   public-resume:subdomain: cv
   public-resume:bucketName: danielteycheney-cv-site-123456789012
   # Optional: uncomment to select a specific public hosted zone.
   # public-resume:hostedZoneId: Z28T3HGN0GB1AY
```

Replace the example bucket suffix with a globally unique, lowercase S3 bucket name before deploying. The bucket name must match the `bucketName` value in `Pulumi.prod.yaml`. Then run:

```sh
pulumi preview
pulumi up
```

The full site domain is composed from `subdomain` and `rootDomain`. Choose a globally unique S3 bucket name using lowercase letters, numbers, and hyphens. The stack looks up the public Route 53 hosted zone by `rootDomain`; it does not create another hosted zone or change the domain registration. If multiple matching zones exist, select the intended one with `pulumi config set hostedZoneId ZONE_ID`. ACM DNS validation and the subdomain alias record are created automatically.

## DNS and approval

You normally do not need to manually approve creation of `cv.danielteycheney.com`. During `pulumi up`, Pulumi asks for approval before applying changes; use `pulumi up --yes` only in a trusted automated pipeline.

The stack automatically:

1. Requests an ACM certificate for `cv.danielteycheney.com` in `us-east-1`.
2. Creates the ACM DNS validation record in the existing Route 53 hosted zone.
3. Waits for certificate validation.
4. Creates the CloudFront distribution.
5. Creates the Route 53 alias record for `cv.danielteycheney.com`.

The exception is domain delegation. If `danielteycheney.com` is not using the Route 53 hosted zone's name servers, manually update the name servers at the registrar first. No separate subdomain approval is normally required.

After deployment:

```sh
pulumi stack output url
curl -I https://cv.danielteycheney.com
```

CloudFront can take several minutes to finish its first deployment. DNS and certificate changes can also take time to propagate.

## Updating the resume

Rebuild the site after changing `resume.json`, then run `pulumi up` again:

```sh
cd ..
npx resume export site/index.html --format html --theme stackoverflow
PUPPETEER_EXECUTABLE_PATH="$(node -e 'process.stdout.write(require("puppeteer").executablePath())')" \
   npx resume export site/resume.pdf --format pdf --theme stackoverflow
cp resume.json site/resume.json
cd infra
uv sync
pulumi up
```

For CI, install `uv`, run `uv sync`, store the Pulumi access token in the CI secret store when using Pulumi Cloud, and authenticate AWS with GitHub Actions OIDC. Do not commit AWS access keys, Pulumi secrets, or the `infra/.venv` directory.

## Remove the stack

```sh
pulumi destroy
pulumi stack rm prod
```

The S3 bucket is versioned, so review retained object versions before deleting the bucket if you later add a retention policy or other production safeguards.