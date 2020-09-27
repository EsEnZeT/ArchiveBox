__package__ = 'archivebox.extractors'

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

from ..index.schema import Link, ArchiveResult, ArchiveOutput, ArchiveError
from ..util import (
    enforce_types,
    is_static_file,
    download_url,
    htmldecode,
)
from ..config import (
    TIMEOUT,
    CHECK_SSL_VALIDITY,
    SAVE_TITLE,
    CURL_BINARY,
    CURL_VERSION,
    CURL_USER_AGENT,
    setup_django,
)
from ..logging_util import TimedProgress


class TitleParser(HTMLParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_tag = ""
        self.title_og = ""
        self.inside_title_tag = False

    @property
    def title(self):
        return self.title_tag or self.title_og or None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title" and not self.title_tag:
            self.inside_title_tag = True
        elif tag.lower() == "meta" and not self.title_og:
            attrs = dict(attrs)
            if attrs.get("property") == "og:title" and attrs.get("content"):
                self.title_og = attrs.get("content")

    def handle_data(self, data):
        if self.inside_title_tag and data:
            self.title_tag += data.strip()
    
    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.inside_title_tag = False


@enforce_types
def should_save_title(link: Link, out_dir: Optional[str]=None) -> bool:
    # if link already has valid title, skip it
    if link.title and not link.title.lower().startswith('http'):
        return False

    if is_static_file(link.url):
        return False

    return SAVE_TITLE

@enforce_types
def save_title(link: Link, out_dir: Optional[Path]=None, timeout: int=TIMEOUT) -> ArchiveResult:
    """try to guess the page's title from its content"""

    setup_django(out_dir=out_dir)
    from core.models import Snapshot

    output: ArchiveOutput = None
    cmd = [
        CURL_BINARY,
        '--silent',
        '--max-time', str(timeout),
        '--location',
        '--compressed',
        *(['--user-agent', '{}'.format(CURL_USER_AGENT)] if CURL_USER_AGENT else []),
        *([] if CHECK_SSL_VALIDITY else ['--insecure']),
        link.url,
    ]
    status = 'succeeded'
    timer = TimedProgress(timeout, prefix='      ')
    try:
        html = download_url(link.url, timeout=timeout)
        parser = TitleParser()
        parser.feed(html)
        output = parser.title
        if output:
            if not link.title or len(output) >= len(link.title):
                Snapshot.objects.filter(url=link.url, timestamp=link.timestamp).update(title=output)
        else:
            raise ArchiveError('Unable to detect page title')
    except Exception as err:
        status = 'failed'
        output = err
    finally:
        timer.end()

    return ArchiveResult(
        cmd=cmd,
        pwd=str(out_dir),
        cmd_version=CURL_VERSION,
        output=output,
        status=status,
        **timer.stats,
    )
