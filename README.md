# Purpose

The purpose of this tooling is to automate the detection of expiring certs, and
then check if the renewal has been generated and deployed. Ultimately, tickets
will be automatically opened.

# Approach

The tool is invoked with a future date and a list of hosts (or domains). The
tool processes all hosts looking for certificates that are currently unexpired,
and checks to see if they _will_ be expired on the specified future date. If
another cert will be valid on the future date (i.e. the cert has been
reissued), then the host is checked to see if the newer cert is deployed which
will be valid on the future date.

For each host, certificate tuple, the following attributes are then known:
- `needs renewal` - true if this cert will expire before the future date
- `host reachable` - true if we can connect to the host from the tool
- `certificate deployed` - true if the deployed certificate will be valid on
  the future date. Only meaningful if the host is reachable

Certificate information for a host is retrieved from a Certificate Transparency
data store. Note that there may be multiple unexpired certificates for a host.
Usually, just 2: one that will be expired on the future date, and one that will
be valid.

An exemption list, containing items to skip (domains, hosts) is consulted, so
that false positives can be removed from the next report.

TODO: create exemption list maintenance tool to remove decommissioned exemptions after the current cert expires.

TODO: some domains have multiple valid certs at any point in time. Consider treating as "deployed" only the cert being tested. (Rather than any valid at future date.)

TODO: date reported for expiration in "re-issued, unreachable" should be stable, and the "soonest" expiration date. (This may not be meaningful when >2 certs exist.)

# Operation

## Configuration

While you can enter host names on the command line, you may prefer to keep all
relevant hosts in a file.

You may also want to develop and maintain a list of exceptions. The exceptions
file is formatted as yaml, and is described in the source file. The default
name is `exceptions.yaml` and there is a schema available as
`exceptions_schema.json` which is helpful if your editor supports them. (See
development section for more information on the schema.)

The exceptions file supports specifying:
- Certificates for hosts we know are being decommissioned, so no renewal is
  needed. These exceptions are manually entered after someone confirms the
  decom.
- Certificates for hosts that are not on the public net, and thus can not be
  verified as installed. These exceptions are manually entered after someone
  with access confirms the installation.
- Domains that never contain long lived production domains. E.g. a development
  domain with short lived instances.


## Execution

Set up a virtual environment, then invoke "`report-tls-"certs --help`" to view the options.

# Development

This is a normal Python script, with one embellishment. All structured data is
defined in the source, using [Pydantic][pydantic]. This allows a schema to be
generated via:
```bash
$ ./report-tls-certs --generate-schema >exceptions_schema.json
```
Hopefully, you're using an editor that can make use of the schema.

# Deployment

The script can be deployed in a docker container. (For Mozilla use, the docker
container is defined elsewhere, as it includes Mozilla specific data.)

**N.B.:** the tool is built atop typer, which can exhibit odd behavior if not
connected to a PTY. Use the `--tty` option to the `docker run` command to avoid
this.


[pydantic]: https://pydantic-docs.helpmanual.io/
