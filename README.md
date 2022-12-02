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

## Configuration

Installation dependent values need to be specified. They are passed to the
container as environment variables. For convenience during development, you can
also define values in `config.env` file. If that file exists, it will be copied
into the container image.

That file name is excluded from commit by `.gitignore` to avoid committing
infrastructure details. It is assumed you have traditional production methods
for setting envronment values in production.

See [`config.env.template`](config.env.template) for more details if you want to
use this approach.

# Deployment

The scripts can be deployed in a docker container.

**N.B.:** the tool is built atop typer, which can exhibit odd behavior if not
connected to a PTY. Use the `--tty` option to the `docker run` command to avoid
this.

## GCP tips

The following tips apply if you want to run the container outside of a k8s
environment, using a Scheduled Compute Engine VM.

This job can take a long time with many domains (hours - my runs take about 14
hours). The choke point is responsiveness of `crt.sh` site, so mutithreading
does not help, nor does horizontal scaling. Getting a long running container's
host to terminate on container termination is not as-obvious-as-I-thought.
Here's the solution used here.

1. Create your container to:
   - Not use "ENTRYPOINT" in the Dockerfile
   - Use "CMD" to specify default behavior
2. Use [GCP
   process](https://cloud.google.com/compute/docs/containers/deploying-containers#deploying_a_container_on_a_new_vm_instance)
   to create a Container-Optimized OS VM configured to deploy your container,
   with the following options:
    - In the Container section, override the default run command with a
      quick-to-execute command. I use `date`.
    - In the "Custom metadata" section, add a "startup-script" (example below).
      This script will run the container to do the real work, then terminate the
      instance.

This approach minimizes the custom code and permission hacks needed to use other
approaches. The blockers I hit included:
- configuring the VM to have the correct permissions to allow a `docker pull`
  for images in GAR.
  - Container-Optimized OS images do not have the stock `gauth` or `gcloud`
    tools installed. Nor do they have user accessible package mangers to install
    those tools (they are Chrome OS).
- non-cloud optimized base images do not come with docker installed. Yes, that's
  doable in the `startup-script`, but (a) why? and (b) you'll still have
  permission hurdles if your image is stored in GAR.

### startup-script example

N.B. the startup script runs as root. In this case there is little security to
be gained by creating a non-root user to invoke the container.

```bash
#!/bin/bash
# This script should be set as the boot script for VM on GCP

DOCKER_IMAGE=us-central1-docker.pkg.dev/hwine-cc-dev/certificate-certainty/busybox:latest

# It will:
#   - configure docker to send logs to GCP logging
#   - start docker
#   - run the hardcoded container
#   - exit, stopping the VM

set -x

# Send logs to GCP {{{
config_file=/etc/docker/daemon.json
# we want to overwrite the config -- the existing values conflict
echo '{"log-driver":"gcplogs"}' > $config_file
# Send logs to GCP }}}

# Make sure dockerd is running.
systemctl restart docker
# wait for docker to be operational
while !docker ps &>/dev/null; do
  sleep 10
done

# Do the real run
docker run --rm -t $DOCKER_IMAGE; ec=$?
date --iso=sec --utc

# if we had an error, hang around so folks can ssh in
if [[ $ec -ne 0 ]] ; then
    echo "waiting 8 hours for ssh session"
    sleep  28800 # 60 * 60 * 8
    echo "done waiting"
fi
# wait for things to calm down, then shutdown
sleep 60
/sbin/shutdown -h +1
```

[pydantic]: https://pydantic-docs.helpmanual.io/
