# YellowDog Cloud Wizard

<!--ts-->
* [Overview](#overview)
* [YellowDog Prerequisites](#yellowdog-prerequisites)
* [Cloud Wizard for AWS](#cloud-wizard-for-aws)
   * [AWS Account Prequisites](#aws-account-prequisites)
   * [Quickstart Guide (AWS)](#quickstart-guide-aws)
      * [Creation](#creation)
      * [Removal](#removal)
   * [Details of Operation: AWS](#details-of-operation-aws)
      * [Cloud Wizard Setup](#cloud-wizard-setup)
         * [Network Details](#network-details)
         * [AWS Account Setup](#aws-account-setup)
         * [YellowDog Platform Setup](#yellowdog-platform-setup)
      * [Cloud Wizard Teardown](#cloud-wizard-teardown)
      * [Idempotency](#idempotency)
      * [Adding and Removing support for Inbound SSH](#adding-and-removing-support-for-inbound-ssh)
* [Cloud Wizard for GCP](#cloud-wizard-for-gcp)
   * [GCP Prerequisites](#gcp-prerequisites)
   * [Quickstart Guide (GCP)](#quickstart-guide-gcp)
      * [Creation](#creation-1)
      * [Removal](#removal-1)
   * [Details of Operation: GCP](#details-of-operation-gcp)
      * [Cloud Wizard Setup](#cloud-wizard-setup-1)
         * [Network Details](#network-details-1)
         * [GCP Account Setup](#gcp-account-setup)
         * [YellowDog Platform Setup](#yellowdog-platform-setup-1)
      * [Cloud Wizard Teardown](#cloud-wizard-teardown-1)
      * [Idempotency](#idempotency-1)
* [Cloud Wizard for Azure](#cloud-wizard-for-azure)
   * [Azure Account Prequisites](#azure-account-prequisites)
      * [Azure Service Principal Setup Steps](#azure-service-principal-setup-steps)
         * [Adding Custom Role](#adding-custom-role)
   * [Quickstart Guide (Azure)](#quickstart-guide-azure)
      * [Creation](#creation-2)
      * [Removal](#removal-2)
   * [Details of Operation: Azure](#details-of-operation-azure)
      * [Cloud Wizard Setup](#cloud-wizard-setup-2)
         * [Azure Account Setup](#azure-account-setup)
         * [YellowDog Platform Setup](#yellowdog-platform-setup-2)
      * [Cloud Wizard Teardown](#cloud-wizard-teardown-2)
      * [Idempotency](#idempotency-2)
      * [Adding and Removing support for Inbound SSH](#adding-and-removing-support-for-inbound-ssh-1)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Wed Sep 23 15:47:47 BST 2026 -->

<!--te-->

# Overview

YellowDog Cloud Wizard is an **experimental** utility that automates the process of configuring a cloud provider account for use with YellowDog, and for creating YellowDog resources that work with the account. The goal is to make it quick and easy to get from opening a new cloud provider account to using it productively with YellowDog. 

Cloud Wizard currently supports Amazon AWS, Google GCP and Microsoft Azure.

# YellowDog Prerequisites

The `yellowdog-cli` Python package must be installed, with the optional Cloud Wizard dependencies:

```commandline
pip install -U "yellowdog-cli[cloudwizard]"
```

You'll need a YellowDog Platform account, and to have created an **Application** via the [YellowDog Portal](https://portal.yellowdog.co/#/account/applications). The Application must belong to a group that has the following permissions at a minimum: `KEYRING_WRITE`, `COMPUTE_SOURCE_TEMPLATE_WRITE` and `COMPUTE_REQUIREMENT_TEMPLATE_WRITE`. If you make the Application a member of the `administrators` group, it will acquire these rights automatically.

The Application's **Key ID** and **Key Secret** need to be available to the Cloud Wizard command either (1) via the environment variables `YD_KEY` and `YD_SECRET`, or (2) they can be set on the command line using the `--key`/`-k` and `--secret`/`-s` options, or (3) they can be set in a `config.toml` configuration file as follows:

```toml
common.key = "<Insert Key ID>"
common.secret = "<Insert Key Secret>"
```

Environment variables can be set up as follows, inserting your Application key and secret where indicated:

**Linux and macOS**
```commandline
export YD_API_KEY_ID=<Insert your Application Key ID here>
export YD_API_KEY_SECRET=<Insert your Application Key Secret here>
```
**Windows Command Prompt**
```commandline
set YD_API_KEY_ID <Insert your Application Key ID here>
set YD_API_KEY_SECRET <Insert your Application Key Secret here>
```

# Cloud Wizard for AWS

## AWS Account Prequisites

You'll need an AWS account along with AWS access keys for the root user or for another user with the rights to manage IAM users and policies. The access keys will need to be accessible to the Cloud Wizard command either via [environment variables](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html) or via [credential files](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html).

## Quickstart Guide (AWS)

### Creation

Run the Cloud Wizard setup command:

```commandline
yd-cloudwizard --cloud-provider=aws --region-name=eu-west-2 setup
```

Once the command has configured the necessary aspects of your AWS account, it will present a list of AWS Availability Zones. Select the Availability Zone(s) you'd like to use. For example:

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

The command will then proceed to create two YellowDog Compute Source templates for each selected Availability Zone, one for on-demand VMs, one for spot VMs. The command will also create a small selection of Compute Requirement Templates that make use of the Source Templates. All templates created have the prefix `cloudwizard-aws`.

The resources that were created can be inspected in JSON format in the file `cloudwizard-aws-yellowdog-resources.json`.

The Compute Requirement Templates are then available for use in YellowDog provisioning requests via the YellowDog API; note that an `Images ID` must be supplied.

The AWS Key Secret is not displayed during command operation, and is not retained locally, for security reasons. If you wish to display it, use the `--show-secrets` command line option when invoking `yd-cloudwizard`.

At the conclusion of a successful setup, the command will display the YellowDog Keyring name and password. This password will not be displayed again, and is required to claim access to the Keyring on behalf of your YellowDog Portal user account, allowing you to control AWS resources via the Portal.

### Removal

The AWS account settings and resources, and the YellowDog resources that were created can be entirely removed using the `teardown` operation:

```commandline
yd-cloudwizard --cloud-provider=aws --region-name=eu-west-2 teardown
```

All destructive operations will require user confirmation; to avoid this, use the `--yes`/`-y` command line option.

## Details of Operation: AWS

### Cloud Wizard Setup

The Cloud Wizard command is run using: `yd-cloudwizard --cloud-provider=aws --region-name=eu-west-2 setup`.

Run the command with the `--help`/`-h` option to see the available options.

#### Network Details

Cloud Wizard expects to use the default VPC, default subnet(s), and default security group in each AWS region for which your account is enabled. These are set up automatically when you create your AWS account, and must be present for Cloud Wizard to work with your selected regions.

The default **subnets** are provided with a route to a gateway which allows instances to make outbound connections to the Internet. However, no NAT gateway is provided (this is a separately chargeable AWS service), so instances must have public IP addresses to connect to the Internet and specifically to connect back to the YellowDog Platform.

The default **security group** allows unrestricted traffic between instances on the subnet, and allows unrestricted outbound traffic to any address including the public Internet. It allows **no** inbound access from outside the subnet. Hence, if inbound access is required (e.g., SSH access to an instance), this must be added for each default security group in each region for which it is required. Cloud Wizard provides a command for adding and removing SSH access; please see below.

Cloud Wizard will interrogate your AWS account to find out which regions are available, and to determine the default security group for the region, and the default subnet for each availability zone within the region.

#### AWS Account Setup

Cloud Wizard performs the following actions in your AWS account:

1. It creates a new IAM user called `yellowdog-cloudwizard-user`.
2. It creates a new IAM policy called `yellowdog-cloudwizard-policy`, containing the capabilities required for YellowDog to use your AWS account on behalf of `yellowdog-cloudwizard-user`.
3. It attaches the IAM policy to the IAM user.
4. It creates a new access key for the IAM user; note that the secret access key is not displayed by default and will not be recorded other than in the Credential to be created within YellowDog. To display the secret access key, run the Cloud Wizard command with the `--show-secrets` option.
5. It adds the `AWSServiceRoleForEC2Spot` service linked role to the AWS account. This allows spot instances to be provisioned by YellowDog.

The steps above are essentially an automated version of YellowDog's [AWS account configuration guidelines](https://docs.yellowdog.co/#/knowledge-base/configuring-an-aws-account-for-use-with-yellowdog). Note that the addition of the Service linked role for AWS Fleet is omitted.

Some AWS IAM settings take a little while to percolate through the AWS account. In particular, the `AWSServiceRoleForEC2Spot` service linked role may not take effect immediately, meaning that spot instances cannot be provisioned.

#### YellowDog Platform Setup

Cloud Wizard performs the following actions in your YellowDog Platform account:

1. It creates a YellowDog Keyring called `cloudwizard-aws`. The Keyring name and password are displayed at the end of the Cloud Wizard setup process, and the password will not be displayed again. The Keyring name and password are required for your YellowDog Portal user account to be able to claim the Keyring, and use the credential(s) it contains via the Portal.


2. It creates a Credential called `cloudwizard-aws` contained within the `cloudwizard-aws` Keyring, containing the access key created during the AWS account setup described above.


3. It creates a range of Compute Source Templates, two for each selected AWS availability zone, one for **on-demand** instances and the other for **spot** instances. Each source is given a name with the following pattern: `cloudwizard-aws-eu-west-1a-ondemand`. Instances will use the `cloudwizard-aws/cloudwizard-aws` Credential. Instances will be created with public IP addresses, to permit outbound Internet access. The instance type and Images ID are left as `any`, to be set at higher levels. Any instances created from the source will be tagged with `yd-cloudwizard=yellowdog-cloudwizard-source`.


4. It creates a small range of example Compute Requirement Templates that use the sources above. There are two **static waterfall** provisioning strategy examples, one containing all the on-demand sources, the other containing all the spot sources. Two equivalent templates are created for the **static split** provisioning strategy. All of these templates specify the `t3a.micro` AWS instance type. In addition, an example **dynamic** template is created that will be constrained to AWS instances with 4GB of memory or greater, ordered by lowest cost first. In all cases, no `Images Id` is specified, so this must be supplied at the time of instance provisioning. Each template is given a name such as: `cloudwizard-aws-split-ondemand` or `cloudwizard-aws-dynamic-waterfall-lowestcost`. Note that the default instance type can be overridden using the `--instance-type` command line option.


5. The Compute Source Template and Compute Requirement Template definitions are saved in a JSON resource specification file called `cloudwizard-aws-yellowdog-resources.json`. This file can be edited (for example, to change the instance types), and used with the `yd-create` command to update the resources.

### Cloud Wizard Teardown

All settings and resources created by Cloud Wizard can be removed using `yd-cloudwizard --cloud-provider=aws --region-name=eu-west-2 teardown`. All destructive steps will require user confirmation unless the `--yes`/`-y` option is used.

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

To add an inbound SSH rule to the default security group for a region, Cloud Wizard provides a convenient `add-ssh` option:

`yd-cloudwizard --cloud-provider=aws --region-name=eu-west-2 add-ssh`

The rule can be removed using:

`yd-cloudwizard --cloud-provider=aws --region-name=eu-west-2 remove-ssh`

# Cloud Wizard for GCP

## GCP Prerequisites

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

Run the Cloud Wizard setup command:

```commandline
yd-cloudwizard --cloud-provider=gcp --credentials-file=credentials.json setup
```

Once the command has discovered the GCP regions in which your service account has a default subnet, it will present them in a list. Select the regions for which to create YellowDog Compute Source Templates, e.g.:

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
The command will then proceed to create two YellowDog Compute Source templates for each selected region, one for on-demand VMs, one for spot VMs. The command will also create a small selection of Compute Requirement Templates that make use of the Source Templates. All templates created have the prefix `cloudwizard-gcp`.

The resources that were created can be inspected in JSON format in the file `cloudwizard-gcp-yellowdog-resources.json`.

The Compute Requirement Templates are then available for use in YellowDog provisioning requests via the YellowDog API; note that an `Images ID` must be supplied.

At the conclusion of a successful setup, the command will display the YellowDog Keyring name and password. This password will not be displayed again, and is required to claim access to the Keyring on behalf of your YellowDog Portal user account, allowing you to control GCP resources via the Portal.

### Removal

The GCP account  and YellowDog resources that were created can be entirely removed using the `teardown` operation:

```commandline
yd-cloudwizard --cloud-provider=gcp --credentials-file=credentials.json teardown
```

All destructive operations will require user confirmation; to avoid this, use the `--yes`/`-y` command line option.

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

1. It creates a YellowDog Keyring called `cloudwizard-gcp`. The Keyring name and password are displayed at the end of the Cloud Wizard setup process, and the password will not be displayed again. The Keyring name and password are required for your YellowDog Portal user account to be able to claim the Keyring, and use the credential(s) it contains via the Portal.


2. It creates a Credential called `cloudwizard-gcp` contained within the `cloudwizard-gcp` Keyring, containing the credentials in the supplied JSON file.


3. It creates a range of Compute Source Templates, two for each selected GCP region, one for **on-demand** instances and the other for **spot** instances. Each source is given a name with the following pattern: `cloudwizard-gcp-europe-west1-ondemand`. Instances will use the `cloudwizard-gcp/cloudwizard-gcp` Credential. Instances will be created with public IP addresses, to permit outbound Internet access. The instance type and Images ID are left as `any`, to be set at higher levels.


4. It creates a small range of example Compute Requirement Templates that use the sources above. There are two **static waterfall** provisioning strategy examples, one containing all the on-demand sources, the other containing all the spot sources. Two equivalent templates are created for the **static split** provisioning strategy. All of these templates specify the `f1-micro` GCP instance type by default. In addition, an example **dynamic** template is created that will be constrained to GCP instances with 4GB of memory or greater, ordered by lowest cost first. In all cases, no `Images Id` is specified, so this must be supplied at the time of instance provisioning. Each template is given a name such as: `cloudwizard-gcp-split-ondemand` or `cloudwizard-gcp-dynamic-waterfall-lowestcost`. Note that the default instance type can be overridden using the `--instance-type` command line option.


5. The Compute Source Template and Compute Requirement Template definitions are saved in a JSON resource specification file called `cloudwizard-gcp-yellowdog-resources.json`. This file can be edited (for example, to change the instance types), and used with the `yd-create` command to update the resources.

###  Cloud Wizard Teardown

All settings and resources created by Cloud Wizard can be removed using `yd-cloudwizard --cloud-provider=gcp --credentials-file=credentials.json teardown`. All destructive steps will require user confirmation unless the `--yes`/`-y` option is used.

The following actions are taken in the **YellowDog account**:

1. All Compute Source Templates and Compute Requirement Templates with names starting with `cloudwizard-gcp` are removed.
2. The `cloudwizard-gcp` Keyring is removed.

### Idempotency

In general, it's safe to invoke Cloud Wizard multiple times for both setup and teardown operations. Depending on the setting/resource it will be ignored if present, or the user will be asked to confirm deletion/replacement.

The Compute Source and Compute Requirement templates will be updated, and may differ in their contents if different regions are selected during each invocation. The resource specification JSON file will be overwritten.

# Cloud Wizard for Azure

## Azure Account Prequisites

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
13. Click on **Privileged adminstrator roles** and select the **Contributor** role. Click on **Next**.
14. Click on **Select members** and type **yellowdog-app** into the **Search by name or email address** search box.
15. Select **yellowdog-app** and click on **Select**.
16. Click on **Next** then **Review and assign**.

#### Adding Custom Role

You can also add a **custom role** to provide fine-tuned permissions to your **yellowdog-app Service Principal**.
Here is a complete list of the permissions your custom role will need:
```
Microsoft.Resources/subscriptions/read
Microsoft.Resources/subscriptions/resourceGroups/write
Microsoft.Resources/subscriptions/resourceGroups/read
Microsoft.Network/virtualNetworks/write
Microsoft.Network/virtualNetworks/read
Microsoft.Network/networkSecurityGroups/write
Microsoft.Network/networkSecurityGroups/read
Microsoft.Network/networkSecurityGroups/securityRules/write
Microsoft.Network/networkSecurityGroups/securityRules/read
Microsoft.Network/networkSecurityGroups/join/action
Microsoft.Network/virtualNetworks/subnets/write
Microsoft.Network/virtualNetworks/subnets/read
```

1. Click on **+ Add** and select **Add custom role**. 
2. Click on **Permissions** and add the permissions from the above list. Click on **Review + Create**. 
3. Click on **+ Add** and click on **Add role assignment** into the **Search by name or email address** search box type **yellowdog-app**.
4. Select **yellowdog-app** and click on **Select**. 
5. Click on **Next** then **Review and assign**.

Your Azure account is now prepared for use with YellowDog.

Cloud Wizard requires the following environment variables to be set in order to access your Azure account:

```
AZURE_SUBSCRIPTION_ID=<Use the 'Subscription ID' recorded above>
AZURE_TENANT_ID=<Use the 'Directory (tenant) ID' recorded above>
AZURE_CLIENT_ID=<Use the 'Application (client) ID' recorded above>
AZURE_CLIENT_SECRET=<Use the client secret 'Value' recorded above>
```

Please treat the `AZURE_CLIENT_SECRET` **very securely** -- it allows full access to your Azure account.

## Quickstart Guide (Azure)

### Creation

Run the Cloud Wizard setup command:

```commandline
yd-cloudwizard --cloud-provider=azure setup
```

The command will present a list of Azure regions, allowing you to choose which regions you'd like to use with YellowDog: 

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

Cloud Wizard will then proceed to create various resources for each selected Azure region, in the Azure account. Then, it will create a YellowDog Keyring and Credentials, and two YellowDog Compute Source templates for each selected Availability Zone, one for on-demand VMs, one for spot VMs. The command will also create a small selection of Compute Requirement Templates that make use of the Source Templates. All templates created have the prefix `cloudwizard-azure`.

The resources that were created can be inspected in JSON format in the file `cloudwizard-azure-yellowdog-resources.json`.

The Compute Requirement Templates are then available for use in YellowDog provisioning requests via the YellowDog API; note that an `Images ID` must be supplied.

At the conclusion of a successful setup, the command will display the YellowDog **Keyring name and password**. This password will not be displayed again, and is required to claim access to the Keyring on behalf of your YellowDog Portal user account, allowing you to control Azure resources via the Portal.

### Removal

The Azure account settings and resources and the YellowDog resources that were created by Cloud Wizard can be entirely removed using the `teardown` operation:

```commandline
yd-cloudwizard --cloud-provider=azure teardown
```

All destructive operations will require user confirmation; to avoid this, use the `--yes`/`-y` command line option.

## Details of Operation: Azure

### Cloud Wizard Setup

The Cloud Wizard command is run using: `yd-cloudwizard --cloud-provider=azure setup`.

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

1. It creates a YellowDog Keyring called `cloudwizard-azure`. The Keyring name and password are displayed at the end of the Cloud Wizard setup process, and the password will not be displayed again. The Keyring name and password are required for your YellowDog Portal user account to be able to claim the Keyring, and use the credential(s) it contains via the Portal.


2. It creates a Credential called `cloudwizard-azure` contained within the `cloudwizard-azure` Keyring.


3. It creates a range of Compute Source Templates, two for each selected Azure region, one for **on-demand** instances and the other for **spot** instances. Each source is given a name with the following pattern: `cloudwizard-azure-northeurope-ondemand`. Instances will use the `cloudwizard-azure/cloudwizard-azure` Credential. Instances will be created with public IP addresses, to permit outbound Internet access. The instance type and Images ID are left as `any`, to be set at higher levels.


4. It creates a small range of example Compute Requirement Templates that use the sources above. There are two **static waterfall** provisioning strategy examples, one containing all the on-demand sources, the other containing all the spot sources. Two equivalent templates are created for the **static split** provisioning strategy. All of these templates specify the `Standard_A1_v2` Azure instance type. In addition, an example **dynamic** template is created that will be constrained to Azure instances with 4GB of memory or greater, ordered by lowest cost first. In all cases, no `Images Id` is specified, so this must be supplied at the time of instance provisioning. Each template is given a name such as: `cloudwizard-azure-split-ondemand` or `cloudwizard-azure-dynamic-waterfall-lowestcost`. Note that the default instance type can be overridden using the `--instance-type` command line option when running Cloud Wizard.


5. The Compute Source Template and Compute Requirement Template definitions are saved in a JSON resource specification file called `cloudwizard-azure-yellowdog-resources.json`. This file can be edited (for example, to change the instance types), and used with the `yd-create` command to update the resources.

### Cloud Wizard Teardown

All settings and resources created by Cloud Wizard can be removed using `yd-cloudwizard --cloud-provider=azure teardown`. All destructive steps will require user confirmation unless the `--yes`/`-y` option is used.

The following actions are taken in the **YellowDog account**:

1. All Compute Source Templates and Compute Requirement Templates with names starting with `cloudwizard-azure` are removed.
2. The `cloudwizard-azure` Keyring is removed.

In the **Azure account**, all resource groups with names starting with **yellowdog-cloudwizard-rg-** are removed. This will remove all resources contained within these resource groups. Note that this action is asynchronous, so it might take a few minutes after the Cloud Wizard script has ended for Azure to conclude its deletions.

### Idempotency

In general, it's safe to invoke Cloud Wizard multiple times for both setup and teardown operations. Depending on the setting/resource it will be ignored if present, or the user will be asked to confirm deletion/replacement.

If there are multiple invocations of `setup` the Compute Source and Compute Requirement templates will be updated, and may differ in their contents if different regions are selected during each invocation, and the resource specification JSON file will be overwritten. No resource groups will be deleted as part of a `setup` operation.

### Adding and Removing support for Inbound SSH

To add an inbound SSH rule to the Cloud Wizard security group for a region, Cloud Wizard provides a convenient `add-ssh` option:

`yd-cloudwizard --cloud-provider=azure --region-name=northeurope add-ssh`

The rule can be removed using:

`yd-cloudwizard --cloud-provider=azure --region-name=northeurope remove-ssh`
