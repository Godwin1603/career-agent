from urllib.parse import urlparse

from src.jobs.dto import ParsedJob


class JobNormalizer:
    """
    Normalizes parsed job fields (e.g., removing tracking params, portal detection).
    """

    KNOWN_PORTALS = {
        "greenhouse.io": "greenhouse",
        "boards.greenhouse.io": "greenhouse",
        "lever.co": "lever",
        "jobs.lever.co": "lever",
        "workday.com": "workday",
        "myworkdayjobs.com": "workday",
        "ashbyhq.com": "ashby",
        "jobs.ashbyhq.com": "ashby",
        "breezy.hr": "breezy",
        "workable.com": "workable",
        "applytojob.com": "jazzhr",
    }

    @classmethod
    def normalize(cls, dto: ParsedJob) -> ParsedJob:
        # Detect portal from URL
        # TODO(tech-debt): Portal detection should eventually use the PortalConfig table
        # when that feature is implemented, instead of relying on this hardcoded list.
        if dto.application_url:
            parsed_url = urlparse(dto.application_url)
            netloc = parsed_url.netloc.lower()

            # Remove www.
            if netloc.startswith("www."):
                netloc = netloc[4:]

            for domain, portal_name in cls.KNOWN_PORTALS.items():
                if netloc == domain or netloc.endswith("." + domain):
                    dto.detected_portal = portal_name
                    break

        # Trim strings
        if dto.company_name:
            dto.company_name = dto.company_name.strip()
        if dto.role_title:
            dto.role_title = dto.role_title.strip()
        if dto.location:
            dto.location = dto.location.strip()

        return dto
