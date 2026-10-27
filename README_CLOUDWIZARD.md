# YellowDog Cloud Wizard

<!--ts-->
* [Overview](#overview)
* [YellowDog Prerequisites](#yellowdog-prerequisites)
* [Cloud Wizard for AWS](#cloud-wizard-for-aws)
   * [AWS Account Prerequisites](#aws-account-prerequisites)
   * [Quickstart Guide (AWS)](#quickstart-guide-aws)
      * [Creation](#creation)
         * [Details](#details)
      * [Removal](#removal)
   * [Details of Operation: AWS](#details-of-operation-aws)
      * [Cloud Wizard Setup](#cloud-wizard-setup)
         * [Network Details](#network-details)
         * [AWS Account Setup](#aws-account-setup)
         * [YellowDog Platform Setup](#yellowdog-platform-setup)
      * [Cloud Wizard Teardown](#cloud-wizard-teardown)
      * [Idempotency](#idempotency)
      * [Adding and Removing support for Inbound SSH](#adding-and-removing-support-for-inbound-ssh)
         * [Details](#details-1)
* [Cloud Wizard for GCP](#cloud-wizard-for-gcp)
   * [GCP Prerequisites](#gcp-prerequisites)
   * [Quickstart Guide (GCP)](#quickstart-guide-gcp)
      * [Creation](#creation-1)
         * [Details](#details-2)
      * [Removal](#removal-1)
   * [Details of Operation: GCP](#details-of-operation-gcp)
      * [Cloud Wizard Setup](#cloud-wizard-setup-1)
         * [Network Details](#network-details-1)
         * [GCP Account Setup](#gcp-account-setup)
         * [YellowDog Platform Setup](#yellowdog-platform-setup-1)
      * [Cloud Wizard Teardown](#cloud-wizard-teardown-1)
      * [Idempotency](#idempotency-1)
* [Cloud Wizard for Azure](#cloud-wizard-for-azure)
   * [Azure Account Prerequisites](#azure-account-prerequisites)
      * [Azure Service Principal Setup Steps](#azure-service-principal-setup-steps)
         * [Adding Custom Role](#adding-custom-role)
   * [Quickstart Guide (Azure)](#quickstart-guide-azure)
      * [Creation](#creation-2)
         * [Details](#details-3)
      * [Removal](#removal-2)
   * [Details of Operation: Azure](#details-of-operation-azure)
      * [Cloud Wizard Setup](#cloud-wizard-setup-2)
         * [Azure Account Setup](#azure-account-setup)
         * [YellowDog Platform Setup](#yellowdog-platform-setup-2)
      * [Cloud Wizard Teardown](#cloud-wizard-teardown-2)
      * [Idempotency](#idempotency-2)
      * [Adding and Removing support for Inbound SSH](#adding-and-removing-support-for-inbound-ssh-1)
* [Using What Cloud Wizard Created](#using-what-cloud-wizard-created)
   * [Claim the Keyring](#claim-the-keyring)
   * [See the Templates](#see-the-templates)
   * [Provision From Them](#provision-from-them)
   * [Try a Dynamic Template First](#try-a-dynamic-template-first)
   * [Use Another Instance Type](#use-another-instance-type)
* [Options, Errors and Exit Codes](#options-errors-and-exit-codes)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:14:05 GMT 2026 -->

<!--te-->

# Overview

YellowDog Cloud Wizard is an **experimental** utility that configures a cloud provider account for use with YellowDog, and creates YellowDog resources that work with the account. The goal is to make it quick and easy to get from opening a new cloud provider account to using it productively with YellowDog.

Cloud Wizard supports Amazon AWS, Google GCP and Microsoft Azure. For example, to set up an AWS account for YellowDog:

```commandline
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 setup
```

The same command with `teardown` in place of `setup` removes what it created. The sections below cover each provider in turn, then [how to use what Cloud Wizard created](#using-what-cloud-wizard-created). [Options, Errors and Exit Codes](#options-errors-and-exit-codes) covers the provider names, what is refused, and how a run that fails part-way ends.

# YellowDog Prerequisites

The `yellowdog-cli` Python package must be installed, with the optional Cloud Wizard dependencies:

```commandline
pip install -U "yellowdog-cli[cloudwizard]"
```

You'll need a YellowDog Platform account, and an **Application** created in the [YellowDog Portal](https://portal.yellowdog.co/#/account/applications). The Application must belong to a group that has at least the `KEYRING_WRITE`, `COMPUTE_SOURCE_TEMPLATE_WRITE` and `COMPUTE_REQUIREMENT_TEMPLATE_WRITE` permissions. A member of the `administrators` group has these permissions already.

Cloud Wizard needs the Application's **Key ID** and **Key Secret**. Give them in one of three ways:

1. The environment variables `YD_KEY` and `YD_SECRET`.
2. The `--key`/`-k` and `--secret`/`-s` command line options.
3. A `config.toml` configuration file:

```toml
common.key = "<Insert Key ID>"
common.secret = "<Insert Key Secret>"
```

Environment variables can be set up as follows, inserting your Application key and secret where indicated:

**Linux and macOS**
```commandline
export YD_KEY=<Insert your Application Key ID here>
export YD_SECRET=<Insert your Application Key Secret here>
```
**Windows Command Prompt**
```commandline
set YD_KEY=<Insert your Application Key ID here>
set YD_SECRET=<Insert your Application Key Secret here>
```

# Cloud Wizard for AWS

## AWS Account Prerequisites

You'll need an AWS account along with AWS access keys for the root user or for another user with the rights to manage IAM users and policies. The access keys will need to be accessible to the Cloud Wizard command either via [environment variables](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html) or via [credential files](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html).

## Quickstart Guide (AWS)

### Creation

To set up an AWS account for YellowDog, run `setup`:

```commandline
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 setup
```

Once the command has configured your AWS account, it presents a list of the AWS Availability Zones in the regions your account has enabled. Select the Availability Zones you'd like to use. For example:

```commandline
2023-10-23 10:37:25 : Please select the AWS availability zones for which to create YellowDog Source Templates
2023-10-23 10:37:25 : Displaying matching AWS Availability Zones(s):

    ┌─────┬─────────────────────┬──────────────────────────┬─────────────────────────────┐
    │   # │ Availability Zone   │ Default Subnet ID        │ Default Security Group ID   │
    ├─────┼─────────────────────┼──────────────────────────┼─────────────────────────────┤
    │   1 │ eu-west-1a          │ subnet-0822cd9a5f590a606 │ sg-06092420b42475007        │
    │   2 │ eu-west-1b          │ subnet-0a94cd2ec3e925648 │ sg-06092420b42475007        │
    │   3 │ eu-west-1c          │ subnet-0c6b29562e2c5b44e │ sg-06092420b42475007        │
    │   4 │ eu-west-2a          │ subnet-071832b5cf5c86f78 │ sg-031ed23c7961e3b25        │
    │   5 │ eu-west-2b          │ subnet-0c9dccd7e1ef4ed10 │ sg-031ed23c7961e3b25        │
    │   6 │ eu-west-2c          │ subnet-09b1e54baa4282823 │ sg-031ed23c7961e3b25        │
    └─────┴─────────────────────┴──────────────────────────┴─────────────────────────────┘

2023-10-23 10:37:25 : Please select items (e.g.: 1,2,4-7 / *) or press <Return> to cancel: 1-6
2023-10-23 10:37:35 : Selected item number(s): 1, 2, 3, 4, 5, 6
2023-10-23 10:37:35 : Creating YellowDog Compute Source Templates
```

The command then creates two YellowDog Compute Source Templates for each selected Availability Zone, one for on-demand VMs and one for spot VMs. It also creates a small selection of Compute Requirement Templates that use the Source Templates. All the templates are named with the prefix `cloudwizard-aws`, in the `cloudwizard-aws` namespace.

At the end of setup, the command displays the YellowDog Keyring name and password. Make a note of the password: it is not displayed again. You need it to [claim the Keyring](#claim-the-keyring) for your YellowDog Portal user account, which lets you control AWS resources from the Portal.

The Compute Requirement Templates are then ready for provisioning, which must supply an image (an `Images ID`): see [Using What Cloud Wizard Created](#using-what-cloud-wizard-created).

#### Details

**Namespace.** From another namespace, a template is named with its namespace, for example `cloudwizard-aws/cloudwizard-aws-split-ondemand`.

**The resource file.** The definitions of the Compute Source and Compute Requirement Templates are saved as JSON in the file `cloudwizard-aws-yellowdog-resources.json`. The Keyring and its Credential are left out. An existing file is replaced only after confirmation.

**The AWS secret.** The AWS Key Secret is not displayed while the command runs, and is not kept locally, for security reasons. To display it, add the `--show-secrets` option.

**The Keyring password.** The password is displayed even if a later step failed, and even with `--quiet`.

### Removal

To remove the AWS account settings and resources, and the YellowDog resources, that Cloud Wizard created, run `teardown`:

```commandline
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 teardown
```

Every destructive operation asks for confirmation first. To skip the confirmations, add `--yes`/`-y`.

## Details of Operation: AWS

### Cloud Wizard Setup

The Cloud Wizard command is run using: `yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 setup`.

Run the command with the `--help`/`-h` option to see the available options.

#### Network Details

Cloud Wizard expects to use the default VPC, default subnet(s), and default security group in each AWS region for which your account is enabled. These are set up automatically when you create your AWS account, and must be present for Cloud Wizard to work with your selected regions.

The default **subnets** are provided with a route to a gateway which allows instances to make outbound connections to the Internet. However, no NAT gateway is provided (this is a separately chargeable AWS service), so instances must have public IP addresses to connect to the Internet and specifically to connect back to the YellowDog Platform.

The default **security group** allows unrestricted traffic between instances on the subnet, and allows unrestricted outbound traffic to any address including the public Internet. It allows **no** inbound access from outside the subnet. Hence, if inbound access is required (e.g., SSH access to an instance), this must be added for each default security group in each region for which it is required. Cloud Wizard provides a command for adding and removing SSH access; please see below.

Cloud Wizard asks your AWS account which regions are available. In each region it finds the default security group (the security group named `default` in the region's default VPC) and the default subnet for each availability zone.

`setup` needs a region, to check that the access key it creates works for EC2. It uses `--region-name`, else the default region of your AWS configuration (`AWS_DEFAULT_REGION`, or `region` in `~/.aws/config`). Without either, it stops before creating anything.

#### AWS Account Setup

Cloud Wizard performs the following actions in your AWS account:

1. It creates a new IAM user called `yellowdog-cloudwizard-user`.
2. It creates a new IAM policy called `yellowdog-cloudwizard-policy`, containing the capabilities required for YellowDog to use your AWS account on behalf of `yellowdog-cloudwizard-user`.
3. It attaches the IAM policy to the IAM user.
4. It creates a new access key for the IAM user. The secret access key is not displayed (unless you add `--show-secrets`), and is recorded only in the Credential Cloud Wizard creates in YellowDog.
5. It adds the `AWSServiceRoleForEC2Spot` service linked role to the AWS account. This allows YellowDog to provision spot instances.

These steps automate YellowDog's [AWS account configuration guidelines](https://docs.yellowdog.co/#/knowledge-base/configuring-an-aws-account-for-use-with-yellowdog), except that the Service linked role for AWS Fleet is not added.

Some AWS IAM settings take a little while to percolate through the AWS account. In particular, the `AWSServiceRoleForEC2Spot` service linked role may not take effect immediately, meaning that spot instances cannot be provisioned.

#### YellowDog Platform Setup

Cloud Wizard performs the following actions in your YellowDog Platform account:

1. It creates a YellowDog Keyring called `cloudwizard-aws`. The Keyring name and password are displayed at the end of setup, and the password is not displayed again. Your YellowDog Portal user account needs them to claim the Keyring and use the credentials it contains.
2. It creates a Credential called `cloudwizard-aws` contained within the `cloudwizard-aws` Keyring, containing the access key created during the AWS account setup described above.
3. It creates Compute Source Templates, two for each selected AWS availability zone: one for **on-demand** instances and one for **spot** instances. They are named like `cloudwizard-aws-eu-west-1a-ondemand`. Their instances use the `cloudwizard-aws/cloudwizard-aws` Credential, and have public IP addresses for outbound Internet access. The instance type and Images ID are left as `any`, to be set at higher levels. Any instances created from the source are tagged with `yd-cloudwizard=yellowdog-cloudwizard-source`.
4. It creates seven example Compute Requirement Templates that use the sources above, named like `cloudwizard-aws-split-ondemand` or `cloudwizard-aws-dynamic-split-lowestcost`:
   - Two **static waterfall** templates, one over all the on-demand sources and one over all the spot sources.
   - Two **static split** templates, over the same sources.
   - A fifth static template, `cloudwizard-aws-waterfall-spot-to-ondemand`, using the waterfall strategy over all the spot sources and then all the on-demand ones.
   - Two **dynamic** templates, one waterfall and one split, constrained to AWS instances with 4GB of memory or more, ordered by lowest cost first.

   The static templates use the `t3a.micro` AWS instance type, unless `--instance-type` gives another. None of the templates specifies an `Images Id`, so one must be supplied when instances are provisioned.
5. It saves the Compute Source Template and Compute Requirement Template definitions in a JSON resource specification file called `cloudwizard-aws-yellowdog-resources.json`. You can edit this file (for example, to change the instance types) and update the resources from it with `yd resource create`. Without `--instance-type`, the file holds the instance type as the variable `{{instance_type:=<default>}}`, so `yd resource create -v instance_type=t3a.small cloudwizard-aws-yellowdog-resources.json` creates the templates again with another type (see [Use Another Instance Type](#use-another-instance-type)).

### Cloud Wizard Teardown

To remove everything Cloud Wizard created, run:

```commandline
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 teardown
```

Every destructive step asks for confirmation first, unless you add `--yes`/`-y`.

The following actions are taken in the **YellowDog account**:

1. All Compute Source Templates and Compute Requirement Templates with names starting with `cloudwizard-aws` are removed.
2. The `cloudwizard-aws` Keyring is removed.

The following actions are taken in the **AWS account**:

1. The access key for `yellowdog-cloudwizard-user` is deleted.
2. The IAM policy `yellowdog-cloudwizard-policy` is detached from the user.
3. The IAM policy `yellowdog-cloudwizard-policy` is deleted.
4. The user `yellowdog-cloudwizard-user` is deleted.
5. The `AWSServiceRoleForEC2Spot` service linked role is removed.

### Idempotency

In general, it's safe to invoke Cloud Wizard multiple times for both setup and teardown operations. Depending on the setting/resource it will be ignored if present, or the user will be asked to confirm deletion/replacement.

If there are multiple invocations of `setup`, then the AWS access key and YellowDog Credential will be updated (at the user's option). Also, the Compute Source and Compute Requirement templates will be updated, and may differ in their contents if different availability zones are selected during each invocation. The resource specification JSON file will be overwritten.

### Adding and Removing support for Inbound SSH

To allow inbound SSH to your instances in a region, add an SSH rule to the region's default security group with `add-ssh`:

```commandline
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 add-ssh
```

To remove the rule:

```commandline
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 remove-ssh
```

#### Details

**Every region.** Without `--region-name`, `add-ssh` adds the rule to the default security group of every region the account has opted into.

**Confirmation.** The rule allows SSH from anywhere (`0.0.0.0/0`), so `add-ssh` asks for confirmation first, naming the region or the number of regions. `--yes` skips it.

# Cloud Wizard for GCP

## GCP Prerequisites

Use Python 3.11 or later for GCP. On Python 3.10, Google's libraries print a `FutureWarning` as Cloud Wizard starts, and have stopped receiving updates for that version; the setup itself still works.

Ensure you have credentials (keys) for a **GCP Service Account** in a GCP project with the **Compute Engine API** enabled. The credentials should be in the form of a locally downloaded JSON file, of the form:

```json
{
  "type": "service_account",
  "project_id": "my-gcp-project",
  "private_key_id": "<REDACTED>",
  "private_key": "<REDACTED>",
  "client_email": "<REDACTED>-compute@developer.gserviceaccount.com",
  "client_id": "<REDACTED>",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/<REDACTED>-compute%40developer.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
```

## Quickstart Guide (GCP)

### Creation

To set up a GCP project for YellowDog, run `setup`, giving the Service Account's credentials file:

```commandline
yd cloudwizard --cloud-provider=gcp --credentials-file=credentials.json setup
```

The command lists the GCP regions in which your Service Account has a default subnet. Select the regions for which to create YellowDog Compute Source Templates. For example:

```commandline
2023-11-03 11:01:05 : Please select the Google Compute Engine regions for which to create YellowDog Compute Source Templates
2023-11-03 11:01:05 : Displaying matching Region(s):

    ┌─────┬─────────────────────────┐
    │   # │ Name                    │
    ├─────┼─────────────────────────┤
    │   1 │ asia-east1              │
    │   2 │ asia-east2              │
    │   3 │ asia-northeast1         │
    │   4 │ asia-northeast2         │
    │   5 │ asia-northeast3         │
    │   6 │ asia-south1             │
    └─────┴─────────────────────────┘

2023-11-03 11:01:05 : Please select items (e.g.: 1,2,4-7 / *) or press <Return> to cancel:
```

The command then creates two YellowDog Compute Source Templates for each selected region, one for on-demand VMs and one for spot VMs. It also creates a small selection of Compute Requirement Templates that use the Source Templates. All the templates are named with the prefix `cloudwizard-gcp`.

At the end of setup, the command displays the YellowDog Keyring name and password. Make a note of the password: it is not displayed again. You need it to [claim the Keyring](#claim-the-keyring) for your YellowDog Portal user account, which lets you control GCP resources from the Portal.

The Compute Requirement Templates are then ready for provisioning, which must supply an image (an `Images ID`): see [Using What Cloud Wizard Created](#using-what-cloud-wizard-created).

#### Details

**Namespace.** The templates are in the `cloudwizard-gcp` namespace. From another namespace, a template is named with its namespace, for example `cloudwizard-gcp/cloudwizard-gcp-split-ondemand`.

**The resource file.** The definitions of the Compute Source and Compute Requirement Templates are saved as JSON in the file `cloudwizard-gcp-yellowdog-resources.json`. The Keyring and its Credential are left out. An existing file is replaced only after confirmation.

**The Keyring password.** The password is displayed even if a later step failed, and even with `--quiet`.

### Removal

To remove the YellowDog resources that Cloud Wizard created, run `teardown`:

```commandline
yd cloudwizard --cloud-provider=gcp --credentials-file=credentials.json teardown
```

Every destructive operation asks for confirmation first. To skip the confirmations, add `--yes`/`-y`.

## Details of Operation: GCP

### Cloud Wizard Setup

#### Network Details

Cloud Wizard expects to use the `default` VPC in the GCP project, and the `default` subnet in each enabled region. These are created automatically when the Compute Engine API is enabled in the project.

The default **subnets** are provided with a route to a gateway which allows instances to make outbound connections to the Internet. However, no NAT gateway is provided (this is a separately chargeable GCP service), so instances must have public IP addresses to connect to the Internet and specifically to connect back to the YellowDog Platform.

The default **firewall** settings allow unrestricted traffic between instances on the subnet, and allows unrestricted outbound traffic to any address including the public Internet. The firewall also allows SSH and RDP ingress, and ICMP by default.

#### GCP Account Setup

No changes are made to your GCP account.

#### YellowDog Platform Setup

Cloud Wizard performs the following actions in your YellowDog Platform account:

1. It creates a YellowDog Keyring called `cloudwizard-gcp`. The Keyring name and password are displayed at the end of setup, and the password is not displayed again. Your YellowDog Portal user account needs them to claim the Keyring and use the credentials it contains.
2. It creates a Credential called `cloudwizard-gcp` contained within the `cloudwizard-gcp` Keyring, containing the credentials in the supplied JSON file.
3. It creates Compute Source Templates, two for each selected GCP region: one for **on-demand** instances and one for **spot** instances. They are named like `cloudwizard-gcp-europe-west1-ondemand`. Their instances use the `cloudwizard-gcp/cloudwizard-gcp` Credential, and have public IP addresses for outbound Internet access. The instance type and Images ID are left as `any`, to be set at higher levels.
4. It creates seven example Compute Requirement Templates that use the sources above, named like `cloudwizard-gcp-split-ondemand` or `cloudwizard-gcp-dynamic-split-lowestcost`:
   - Two **static waterfall** templates, one over all the on-demand sources and one over all the spot sources.
   - Two **static split** templates, over the same sources.
   - A fifth static template, `cloudwizard-gcp-waterfall-spot-to-ondemand`, using the waterfall strategy over all the spot sources and then all the on-demand ones.
   - Two **dynamic** templates, one waterfall and one split, constrained to GCP instances with 4GB of memory or more, ordered by lowest cost first.

   The static templates use the `f1-micro` GCP instance type, unless `--instance-type` gives another. None of the templates specifies an `Images Id`, so one must be supplied when instances are provisioned.
5. It saves the Compute Source Template and Compute Requirement Template definitions in a JSON resource specification file called `cloudwizard-gcp-yellowdog-resources.json`. You can edit this file (for example, to change the instance types) and update the resources from it with `yd resource create`. Without `--instance-type`, the file holds the instance type as the variable `{{instance_type:=<default>}}`, so `yd resource create -v instance_type=e2-small cloudwizard-gcp-yellowdog-resources.json` creates the templates again with another type (see [Use Another Instance Type](#use-another-instance-type)).

### Cloud Wizard Teardown

To remove everything Cloud Wizard created, run:

```commandline
yd cloudwizard --cloud-provider=gcp --credentials-file=credentials.json teardown
```

Every destructive step asks for confirmation first, unless you add `--yes`/`-y`.

The following actions are taken in the **YellowDog account**:

1. All Compute Source Templates and Compute Requirement Templates with names starting with `cloudwizard-gcp` are removed.
2. The `cloudwizard-gcp` Keyring is removed.

### Idempotency

In general, it's safe to invoke Cloud Wizard multiple times for both setup and teardown operations. Depending on the setting/resource it will be ignored if present, or the user will be asked to confirm deletion/replacement.

The Compute Source and Compute Requirement templates will be updated, and may differ in their contents if different regions are selected during each invocation. The resource specification JSON file will be overwritten.

# Cloud Wizard for Azure

## Azure Account Prerequisites

You'll need an Azure account, a Service Principal created within the account, a client secret created for the Service Principal, and the Contributor role applied to the Service Principal.

### Azure Service Principal Setup Steps

Please see the article [Create a Microsoft Entra application and service principal that can access resources](https://learn.microsoft.com/en-us/entra/identity-platform/howto-create-service-principal-portal) for an overview of the process, then perform the steps outlined below.

1. Sign in to the [Azure Portal](https://portal.azure.com/).
2. Go to the [Microsoft Entra ID home page](https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/Overview) (or search for 'Entra ID' using the top search bar).
3. Click **Add** and select **App Registration**.
4. Select the name for the App Registration; we suggest using **yellowdog-app**. For **Supported account types** use the default of **Accounts in this organizational directory only**. Click **Register**.
5. Make a note of the **Application (client) ID** and the **Directory (tenant) ID**.
6. Under **Client Credentials**, click on **Add a certificate or secret**.
7. Under the default **Client Secrets (0)** tab, click on **+ New client secret**.
8. Enter a **Description** (we suggest **YellowDog**), and choose an **Expiry** period or date using the drop-down menu. Click on **Add**.
9. Make a note of the **Value** of the secret; this will only be shown once.
10. Navigate to your Subscription (usually called **Azure subscription 1** by default), by typing **Subscriptions** in the Azure Portal search bar. Make a note of the **Subscription ID**.
11. In the left hand menu, click on **Access control (IAM)**, and click on **Role assignments** in the horizontal tabs.
12. Click on **+ Add** and select **Add role assignment**.
13. Click on **Privileged administrator roles** and select the **Contributor** role. Click on **Next**.
14. Click on **Select members** and type **yellowdog-app** into the **Search by name or email address** search box.
15. Select **yellowdog-app** and click on **Select**.
16. Click on **Next** then **Review and assign**.

#### Adding Custom Role

You can also add a **custom role** to provide fine-tuned permissions to your **yellowdog-app Service Principal**.

Here is a complete list of the permissions your custom role will need:
```
Microsoft.Resources/subscriptions/read
Microsoft.Resources/subscriptions/locations/read
Microsoft.Resources/subscriptions/resourceGroups/write
Microsoft.Resources/subscriptions/resourceGroups/read
Microsoft.Resources/subscriptions/resourceGroups/delete
Microsoft.Network/virtualNetworks/write
Microsoft.Network/virtualNetworks/read
Microsoft.Network/virtualNetworks/delete
Microsoft.Network/networkSecurityGroups/write
Microsoft.Network/networkSecurityGroups/read
Microsoft.Network/networkSecurityGroups/delete
Microsoft.Network/networkSecurityGroups/securityRules/write
Microsoft.Network/networkSecurityGroups/securityRules/read
Microsoft.Network/networkSecurityGroups/securityRules/delete
Microsoft.Network/networkSecurityGroups/join/action
Microsoft.Network/virtualNetworks/subnets/write
Microsoft.Network/virtualNetworks/subnets/read
Microsoft.Network/virtualNetworks/subnets/delete
```

The `delete` permissions are what `teardown` (which deletes the resource groups Cloud Wizard created, and what is in them) and `remove-ssh` need.

1. Click on **+ Add** and select **Add custom role**. 
2. Click on **Permissions** and add the permissions from the above list. Click on **Review + Create**. 
3. Click on **+ Add**, select **Add role assignment**, and select the custom role you created. Click on **Next**.
4. Click on **Select members** and type **yellowdog-app** into the **Search by name or email address** search box.
5. Select **yellowdog-app** and click on **Select**.
6. Click on **Next** then **Review and assign**.

Your Azure account is now prepared for use with YellowDog.

Cloud Wizard reads your Azure account's details from four environment variables, set from the values you recorded above:

| Variable | Value recorded above |
|:---|:---|
| `AZURE_SUBSCRIPTION_ID` | the **Subscription ID** |
| `AZURE_TENANT_ID` | the **Directory (tenant) ID** |
| `AZURE_CLIENT_ID` | the **Application (client) ID** |
| `AZURE_CLIENT_SECRET` | the client secret's **Value** |

For example, on Linux and macOS:

```commandline
export AZURE_SUBSCRIPTION_ID=3f2b9c1e-7a4d-4e8b-9c62-1d5a0e7f4b38
export AZURE_TENANT_ID=8c1d5e2a-0b3f-4a6c-b7d9-2e4f6a8c0d1b
export AZURE_CLIENT_ID=5a7e9c2b-4d6f-4b1a-8e3c-7f9b1d3e5a20
export AZURE_CLIENT_SECRET=Xq8~kL2pR.vN4tY7wZ1sB3dF6gH9jM0cE5aU_iO
```

Please treat the `AZURE_CLIENT_SECRET` **very securely** -- it allows full access to your Azure account.

## Quickstart Guide (Azure)

### Creation

To set up an Azure account for YellowDog, set the [Azure environment variables](#azure-account-prerequisites) and run `setup`:

```commandline
yd cloudwizard --cloud-provider=azure setup
```

The command lists the Azure regions. Select the regions you'd like to use with YellowDog:

```commandline
2024-01-16 11:34:24 : Please select the Azure regions in which to create resource groups and network resources.
2024-01-16 11:34:24 : *** Note that only the following region(s) contain YellowDog base VM images: ['northeurope'] ***
2024-01-16 11:34:24 : Displaying matching region(s):

    ┌─────┬────────────────────┐
    │   # │ Name               │
    ├─────┼────────────────────┤
    │   1 │ australiacentral   │
    ...
    │  27 │ northcentralus     │
    │  28 │ northeurope        │
    ...
    │  48 │ westus             │
    │  49 │ westus2            │
    │  50 │ westus3            │
    └─────┴────────────────────┘

2024-01-16 11:34:24 : Please select items (e.g.: 1,2,4-7 / *):
```

Cloud Wizard then creates network resources in your Azure account for each selected region. It then creates a YellowDog Keyring and Credential, and two YellowDog Compute Source Templates for each selected region, one for on-demand VMs and one for spot VMs. It also creates a small selection of Compute Requirement Templates that use the Source Templates. All the templates are named with the prefix `cloudwizard-azure`.

At the end of setup, the command displays the YellowDog **Keyring name and password**. Make a note of the password: it is not displayed again. You need it to [claim the Keyring](#claim-the-keyring) for your YellowDog Portal user account, which lets you control Azure resources from the Portal.

The Compute Requirement Templates are then ready for provisioning, which must supply an image (an `Images ID`): see [Using What Cloud Wizard Created](#using-what-cloud-wizard-created).

#### Details

**Namespace.** The templates are in the `cloudwizard-azure` namespace. From another namespace, a template is named with its namespace, for example `cloudwizard-azure/cloudwizard-azure-split-ondemand`.

**The resource file.** The definitions of the Compute Source and Compute Requirement Templates are saved as JSON in the file `cloudwizard-azure-yellowdog-resources.json`. The Keyring and its Credential are left out. An existing file is replaced only after confirmation.

**The Keyring password.** The password is displayed even if a later step failed, and even with `--quiet`.

### Removal

To remove the Azure resources and the YellowDog resources that Cloud Wizard created, run `teardown`:

```commandline
yd cloudwizard --cloud-provider=azure teardown
```

Every destructive operation asks for confirmation first. To skip the confirmations, add `--yes`/`-y`.

## Details of Operation: Azure

### Cloud Wizard Setup

The Cloud Wizard command is run using: `yd cloudwizard --cloud-provider=azure setup`.

Run the command with the `--help`/`-h` option to see the available options.

#### Azure Account Setup

In each selected Azure region, Cloud Wizard performs the following operations:

1. It creates a resource group named **yellowdog-cloudwizard-rg-<region_name>**.
2. Within this resource group it creates a Virtual Network named **yellowdog-cloudwizard-vnet-<region_name>**.
3. It creates a Network Security Group named **yellowdog-cloudwizard-secgrp-<region_name>** within the resource group.
4. It creates a rule within the Network Security Group that allows **outbound HTTPS access**. This is required to allow the YellowDog Agent to connect to the YellowDog Platform.
5. It creates a Subnet named **yellowdog-cloudwizard-subnet-<region_name>** within the resource group Virtual Network, associating it with the Network Security Group above.

The **subnets** are provided with a route to a gateway which allows instances to make outbound connections to the Internet. However, no NAT gateway is provided (this is a separately chargeable Azure service), so instances must have public IP addresses to connect to the Internet and specifically to connect back to the YellowDog Platform.

#### YellowDog Platform Setup

Cloud Wizard performs the following actions in your YellowDog Platform account:

1. It creates a YellowDog Keyring called `cloudwizard-azure`. The Keyring name and password are displayed at the end of setup, and the password is not displayed again. Your YellowDog Portal user account needs them to claim the Keyring and use the credentials it contains.
2. It creates a Credential called `cloudwizard-azure` contained within the `cloudwizard-azure` Keyring.
3. It creates Compute Source Templates, two for each selected Azure region: one for **on-demand** instances and one for **spot** instances. They are named like `cloudwizard-azure-northeurope-ondemand`. Their instances use the `cloudwizard-azure/cloudwizard-azure` Credential, and have public IP addresses for outbound Internet access. The instance type and Images ID are left as `any`, to be set at higher levels.
4. It creates seven example Compute Requirement Templates that use the sources above, named like `cloudwizard-azure-split-ondemand` or `cloudwizard-azure-dynamic-split-lowestcost`:
   - Two **static waterfall** templates, one over all the on-demand sources and one over all the spot sources.
   - Two **static split** templates, over the same sources.
   - A fifth static template, `cloudwizard-azure-waterfall-spot-to-ondemand`, using the waterfall strategy over all the spot sources and then all the on-demand ones.
   - Two **dynamic** templates, one waterfall and one split, constrained to Azure instances with 4GB of memory or more, ordered by lowest cost first.

   The static templates use the `Standard_A1_v2` Azure instance type, unless `--instance-type` gives another. None of the templates specifies an `Images Id`, so one must be supplied when instances are provisioned.
5. It saves the Compute Source Template and Compute Requirement Template definitions in a JSON resource specification file called `cloudwizard-azure-yellowdog-resources.json`. You can edit this file (for example, to change the instance types) and update the resources from it with `yd resource create`. Without `--instance-type`, the file holds the instance type as the variable `{{instance_type:=<default>}}`, so `yd resource create -v instance_type=Standard_B2s cloudwizard-azure-yellowdog-resources.json` creates the templates again with another type (see [Use Another Instance Type](#use-another-instance-type)).

### Cloud Wizard Teardown

To remove everything Cloud Wizard created, run:

```commandline
yd cloudwizard --cloud-provider=azure teardown
```

Every destructive step asks for confirmation first, unless you add `--yes`/`-y`.

The following actions are taken in the **YellowDog account**:

1. All Compute Source Templates and Compute Requirement Templates with names starting with `cloudwizard-azure` are removed.
2. The `cloudwizard-azure` Keyring is removed.

In the **Azure account**, all resource groups with names starting with **yellowdog-cloudwizard-rg-** are removed, with all the resources they contain. Azure deletes them asynchronously, so its deletions may finish a few minutes after the command has ended.

### Idempotency

In general, it's safe to invoke Cloud Wizard multiple times for both setup and teardown operations. Depending on the setting/resource it will be ignored if present, or the user will be asked to confirm deletion/replacement.

Running `setup` again updates the Compute Source and Compute Requirement templates, whose contents differ if different regions are selected. It also overwrites the resource specification JSON file. `setup` never deletes a resource group.

### Adding and Removing support for Inbound SSH

To allow inbound SSH to your instances in a region, add an SSH rule to the region's Cloud Wizard security group with `add-ssh`:

```commandline
yd cloudwizard --cloud-provider=azure --region-name=northeurope add-ssh
```

To remove the rule:

```commandline
yd cloudwizard --cloud-provider=azure --region-name=northeurope remove-ssh
```

The rule allows SSH from anywhere, so `add-ssh` asks for confirmation first, naming the security group and the region. `--yes` skips it.

# Using What Cloud Wizard Created

Once setup has finished, the account has a Keyring holding the cloud provider credential, Compute Source Templates for each region or zone chosen, and seven example Compute Requirement Templates, all in the `cloudwizard-<provider>` namespace (`cloudwizard-aws`, `cloudwizard-gcp` or `cloudwizard-azure`). This section takes AWS as its example; for the others, put `gcp` or `azure` in its place.

## Claim the Keyring

To use the templates from the YellowDog Portal, claim the Keyring there for your Portal user, with the password Cloud Wizard displayed at the end of setup. Until it is claimed, only the Application that ran Cloud Wizard can use the Keyring.

The password is displayed only once. If it has been lost, remove the Keyring and run the setup again:

```shell
yd resource remove --type Keyring cloudwizard-aws
yd cloudwizard --cloud-provider=aws --region-name=eu-west-2 setup
```

The setup creates the Keyring anew, with its Credential, and shows the new password.

## See the Templates

```shell
yd resource list compute-requirement-templates --namespace cloudwizard-aws
yd resource list compute-source-templates --namespace cloudwizard-aws
```

The Compute Requirement Templates differ in how they spread instances across the sources, and which:

| Template | Provisions |
|:---|:---|
| `cloudwizard-aws-split-ondemand`, `cloudwizard-aws-split-spot` | the instances split across all the on-demand, or all the spot, sources |
| `cloudwizard-aws-waterfall-ondemand`, `cloudwizard-aws-waterfall-spot` | the instances from the on-demand, or spot, sources in turn, each used before the next |
| `cloudwizard-aws-waterfall-spot-to-ondemand` | the spot sources in turn, then the on-demand ones |
| `cloudwizard-aws-dynamic-waterfall-lowestcost`, `cloudwizard-aws-dynamic-split-lowestcost` | whichever instance types with 4GB of memory or more cost least, chosen at provisioning time |

The static templates all use the one instance type Cloud Wizard was given (`t3a.micro` on AWS by default). The [YellowDog documentation](https://docs.yellowdog.ai) describes provisioning strategies in full.

## Provision From Them

To provision a Worker Pool from a template, name the template and an image in `config.toml`, then run `yd workerpool provision`. None of the templates names an image, so a Worker Pool or Compute Requirement provisioned from one must. The image must have the YellowDog Agent installed. It is given as an Image Family name, as here, or as a cloud provider image ID, such as an AWS AMI ID from the template's region:

```toml
[workerPool]
templateId = "cloudwizard-aws/cloudwizard-aws-split-ondemand"
imagesId = "image-processing/ubuntu-with-agent"
targetInstanceCount = 1
```

```shell
yd workerpool provision
```

A template in another namespace is named with its namespace, as `cloudwizard-aws/cloudwizard-aws-split-ondemand` is here. The CLI track of [Getting Started](https://docs.yellowdog.ai/#/getting-started/getting-started) in the YellowDog Documentation goes on to a first Task run on such a Worker Pool.

## Try a Dynamic Template First

`--report` shows which sources and instance types a dynamic template would choose, without provisioning anything. With the `[workerPool]` section above in `config.toml`, give it the dynamic template in place of its own:

```shell
yd computerequirement instantiate --report \
    --property workerPool.templateId=cloudwizard-aws/cloudwizard-aws-dynamic-split-lowestcost
```

It ranks the candidate sources and instance types as the Platform would provision from them (see [Test-Running a Dynamic Template](docs/commands.md#test-running-a-dynamic-template)). A static template has no such report, and says so.

## Use Another Instance Type

`--instance-type` gives the static templates another type when they are created. To change it afterwards, recreate them from the resource file setup saved, `cloudwizard-aws-yellowdog-resources.json`, which holds the type as the variable `{{instance_type}}` unless `--instance-type` was given:

```shell
yd resource create -v instance_type=t3a.small cloudwizard-aws-yellowdog-resources.json
```

`yd resource create` updates the templates that already exist, asking first (`--yes` does not ask). A template can also be edited in the file, or a new one added to it, in the same way: see [Creating, Updating and Removing Resources](docs/resources.md).

# Options, Errors and Exit Codes

**Provider names.** `--cloud-provider` takes `aws` (or `amazon`), `gcp` (or `gce`, `google`) or `azure` (or `microsoft`), in any case. Any other name is refused as the command line is read.

**Refused combinations.** These are also refused as the command line is read: GCP without `--credentials-file`, `add-ssh` and `remove-ssh` for GCP, and `add-ssh` and `remove-ssh` for Azure without `--region-name`.

**Errors.** A setup or teardown carries on past a step that fails, so that, for example, a teardown removes everything it can. Each error is reported as it happens. A run that reported any errors ends with `Cloud Wizard finished with N error(s)` and exit code 1.

**A lost Platform connection during teardown.** If a teardown loses its connection to the YellowDog Platform part-way, or its YellowDog credentials are refused, the YellowDog removals left are not attempted, since each would fail the same way. The cloud provider's removals still run. The run ends by saying so, with the failure's own exit code: 8 for the connection, 4 for the credentials. Running the teardown again removes the YellowDog resources that were left.

**A lost Platform connection during Azure setup.** The YellowDog credential is the last thing an Azure setup creates. If the Platform cannot be reached for it, the resource definition file is still saved, and the run ends with the failure's exit code. Running the setup again creates what is missing.
