# a bunch of request helpers
# taken from https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

############################################################
#
#  Setup Default Timeout
#
############################################################
DEFAULT_TIMEOUT = 15  # seconds


class TimeoutHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        self.timeout = DEFAULT_TIMEOUT
        if "timeout" in kwargs:
            self.timeout = kwargs["timeout"]
            del kwargs["timeout"]
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


############################################################
#
#  Set up default retry
#
############################################################


retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    method_whitelist=["HEAD", "GET", "OPTIONS"],
    backoff_factor=1,
)
# adapter = HTTPAdapter(max_retries=retry_strategy)
http = requests.Session()
http.mount("https://", TimeoutHTTPAdapter(max_retries=retry_strategy))
http.mount("http://", TimeoutHTTPAdapter(max_retries=retry_strategy))
