# Authentication

There is no `yd login` command and no interactive sign-in: every `yd` command authenticates with the YellowDog Platform using the **key ID and secret of an Application**, which acts as the CLI's API key. To set up your credentials, run [`yd init`](commands.md#yd-init), which asks for them and writes them to the `[common]` section of `config.toml`:

```toml
[common]
    key = "asdfghjklzxcvb-1234567"
    secret = "qwertyuiopasdfghjklzxcvbnm1234567890qwertyu"
```

Then run [`yd doctor`](commands.md#yd-doctor) to check that your credentials authenticate.

To create an Application, see [YellowDog Prerequisites](../README.md#yellowdog-prerequisites), and add it to a group with the roles your commands need.

The key and secret can also be given with the environment variables `YD_KEY` and `YD_SECRET`, or the command-line options `--key` and `--secret`; see [Specifying Common Properties using the Command Line or Environment Variables](configuration.md#specifying-common-properties-using-the-command-line-or-environment-variables).
