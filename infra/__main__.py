from pathlib import Path

import pulumi
import pulumi_aws as aws


# Read stack-specific values from Pulumi.prod.yaml (or the selected stack's
# config file). rootDomain, subdomain, and bucketName are required there.
config = pulumi.Config()
# DNS names can be written with or without a trailing dot; remove it so the
# composed site hostname does not contain an accidental double dot.
root_domain = config.require("rootDomain").strip(".")
subdomain = config.require("subdomain").strip(".")
domain = f"{subdomain}.{root_domain}"
bucket_name = config.require("bucketName")
# Use an explicitly configured zone when supplied. Otherwise find the public
# hosted zone that exactly matches the root domain.
zone_id = config.get("hostedZoneId") or aws.route53.get_zone(
    name=f"{root_domain}.", private_zone=False
).id
# This is relative to the infra directory by default. Build the HTML here
# before running Pulumi so the files become S3 objects below.
site_directory = Path(config.get("siteDirectory") or "../site").resolve()

# CloudFront only accepts ACM certificates from us-east-1, even though the
# other AWS resources use the stack's configured region.
us_east_1 = aws.Provider("us-east-1", region="us-east-1")

# Request a certificate for the public hostname. Pulumi uses the us-east-1
# provider specifically for this resource because it will be attached to
# CloudFront.
certificate = aws.acm.Certificate(
    "resume-certificate",
    domain_name=domain,
    validation_method="DNS",
    opts=pulumi.ResourceOptions(provider=us_east_1),
)

# ACM supplies the DNS record name, type, and value needed to prove domain
# ownership. These are Outputs, so Pulumi waits for the certificate response
# before creating the validation record in Route 53.
validation_record = aws.route53.Record(
    "resume-certificate-validation",
    zone_id=zone_id,
    name=certificate.domain_validation_options.apply(
        lambda options: options[0].resource_record_name
    ),
    type=certificate.domain_validation_options.apply(
        lambda options: options[0].resource_record_type
    ),
    records=[
        certificate.domain_validation_options.apply(
            lambda options: options[0].resource_record_value
        )
    ],
    ttl=60,
)

# Wait for ACM to observe the validation record and issue the certificate.
# The CloudFront distribution depends on this resource below.
certificate_validation = aws.acm.CertificateValidation(
    "resume-certificate-validation",
    certificate_arn=certificate.arn,
    validation_record_fqdns=[validation_record.fqdn],
    opts=pulumi.ResourceOptions(provider=us_east_1),
)

# The bucket is private by default. Its name is configured separately because
# S3 bucket names must be globally unique across all AWS accounts.
bucket = aws.s3.BucketV2("resume-site", bucket=bucket_name)
# These settings prevent direct public S3 access; website visitors will only
# retrieve files through CloudFront and its origin access control.
aws.s3.BucketPublicAccessBlock(
    "resume-site-public-access-block",
    bucket=bucket.id,
    block_public_acls=True,
    block_public_policy=True,
    ignore_public_acls=True,
    restrict_public_buckets=True,
)
# Keep prior object versions available if an upload replaces or deletes a file.
aws.s3.BucketVersioningV2(
    "resume-site-versioning",
    bucket=bucket.id,
    versioning_configuration=aws.s3.BucketVersioningV2VersioningConfigurationArgs(
        status="Enabled"
    ),
)

# The origin ID is CloudFront's internal label for this S3 origin. OAC signs
# CloudFront's origin requests with SigV4 so the private bucket can authorize
# this distribution without making the bucket public.
origin_id = "resume-s3-origin"
origin_access_control = aws.cloudfront.OriginAccessControl(
    "resume-origin-access-control",
    name="resume-s3-oac",
    description="Allow CloudFront to read the private resume bucket",
    origin_access_control_origin_type="s3",
    signing_behavior="always",
    signing_protocol="sigv4",
)

# Serve the generated files from S3 through CloudFront. The alias and ACM
# certificate make the distribution respond to the configured custom domain.
distribution = aws.cloudfront.Distribution(
    "resume-distribution",
    enabled=True,
    aliases=[domain],
    default_root_object="index.html",
    origins=[
        aws.cloudfront.DistributionOriginArgs(
            # Use the regional S3 API endpoint, not the S3 website endpoint;
            # OAC does not work with S3 website endpoints.
            domain_name=bucket.bucket_regional_domain_name,
            origin_id=origin_id,
            origin_access_control_id=origin_access_control.id,
        )
    ],
    default_cache_behavior=aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
        target_origin_id=origin_id,
        # A resume only needs read requests. HTTP requests are redirected to
        # HTTPS, and cookies are not sent to the origin.
        allowed_methods=["GET", "HEAD"],
        cached_methods=["GET", "HEAD"],
        viewer_protocol_policy="redirect-to-https",
        forwarded_values=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
            query_string=True,
            cookies=aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(
                forward="none"
            ),
        ),
    ),
    restrictions=aws.cloudfront.DistributionRestrictionsArgs(
        geo_restriction=aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
            restriction_type="none"
        )
    ),
    viewer_certificate=aws.cloudfront.DistributionViewerCertificateArgs(
        acm_certificate_arn=certificate_validation.certificate_arn,
        ssl_support_method="sni-only",
        # Require a modern TLS policy for clients connecting to CloudFront.
        minimum_protocol_version="TLSv1.2_2021",
    ),
    # Do not wait for CloudFront's global rollout to finish before Pulumi
    # returns. The distribution can remain InProgress for several minutes.
    wait_for_deployment=False,
    # Pulumi ResourceOptions carries engine settings such as dependencies;
    # these are not AWS distribution properties.
    opts=pulumi.ResourceOptions(depends_on=[certificate_validation]),
)

# Permit only this distribution to read objects from the bucket. Both ARNs are
# Outputs that are unknown until resource creation, so build the policy JSON
# inside apply() after Pulumi has resolved them.
aws.s3.BucketPolicy(
    "resume-site-policy",
    bucket=bucket.id,
    policy=pulumi.Output.all(bucket.arn, distribution.arn).apply(
        lambda values: aws.iam.get_policy_document(
            statements=[
                aws.iam.GetPolicyDocumentStatementArgs(
                    sid="AllowCloudFrontReadOnly",
                    effect="Allow",
                    principals=[
                        aws.iam.GetPolicyDocumentStatementPrincipalArgs(
                            type="Service", identifiers=["cloudfront.amazonaws.com"]
                        )
                    ],
                    actions=["s3:GetObject"],
                    resources=[f"{values[0]}/*"],
                    conditions=[
                        aws.iam.GetPolicyDocumentStatementConditionArgs(
                            test="StringEquals",
                            variable="AWS:SourceArn",
                            values=[values[1]],
                        )
                    ],
                )
            ]
        ).json,
    ),
)

# Upload each file under site_directory using its relative path as the S3 key.
# If the build directory does not exist yet, no site objects are registered,
# so run the JSON Resume export before deploying.
if site_directory.is_dir():
    for file_path in site_directory.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(site_directory).as_posix()
            # Tell browsers the file type; unlisted extensions are served as
            # generic binary data.
            content_type = {
                ".css": "text/css",
                ".html": "text/html",
                ".js": "application/javascript",
                ".json": "application/json",
                ".pdf": "application/pdf",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".svg": "image/svg+xml",
            }.get(file_path.suffix.lower(), "application/octet-stream")
            # Replace slashes in the Pulumi logical name while preserving the
            # original relative path as the object's S3 key.
            aws.s3.BucketObject(
                f"site-{relative_path.replace('/', '-')}",
                bucket=bucket.id,
                key=relative_path,
                source=pulumi.FileAsset(str(file_path)),
                content_type=content_type,
            )

# Route 53 Alias records work with CloudFront and resolve the custom hostname
# directly to the distribution without exposing its changing IP addresses.
aws.route53.Record(
    "resume-dns",
    zone_id=zone_id,
    name=domain,
    type="A",
    aliases=[
        aws.route53.RecordAliasArgs(
            name=distribution.domain_name,
            zone_id=distribution.hosted_zone_id,
            evaluate_target_health=False,
        )
    ],
)

# Export useful values for `pulumi stack output` after deployment.
pulumi.export("url", pulumi.Output.concat("https://", domain))
pulumi.export("distributionId", distribution.id)
pulumi.export("bucketName", bucket.id)