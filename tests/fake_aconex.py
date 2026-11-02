"""A fake Aconex for tests. It answers like the live API (shapes taken from
the Aconex skill's live checks, or Oracle's guides where those weren't
checked) and records every request the gateway makes."""

from __future__ import annotations

import json

import httpx

from gateway.aconex import AconexClient, Settings

TOKEN_HOST = "constructionandengineering.oraclecloud.com"

PROJECTS = b"""<ProjectResults><SearchResults>
  <Project><ProjectId>1001</ProjectId><ProjectName>Harbour St Tower</ProjectName><ProjectCode>HST</ProjectCode></Project>
  <Project><ProjectId>1002</ProjectId><ProjectName>Riverside Depot</ProjectName><ProjectShortName>RSD</ProjectShortName></Project>
</SearchResults></ProjectResults>"""

DIRECTORY = b"""<DirectorySearch><SearchResults>
  <Directory><UserId>501</UserId><UserName>Sam Lee</UserName><OrganizationName>Acme Engineers</OrganizationName><JobTitle>Structural Engineer</JobTitle><Email>sam@acme.example</Email></Directory>
  <Directory><UserId>502</UserId><UserName>Jo Park</UserName><OrganizationName>Builder Co</OrganizationName><JobTitle>Site Manager</JobTitle><Email>jo@builder.example</Email></Directory>
  <Directory><UserId>503</UserId><UserName>Sam Ortiz</UserName><TradingName>Builder Co</TradingName><JobTitle>Project Engineer</JobTitle></Directory>
</SearchResults></DirectorySearch>"""

PERSON = b"""<UserDetails><UserId>501</UserId><FirstName>Sam</FirstName><LastName>Lee</LastName>
  <OrganizationName>Acme Engineers</OrganizationName><Email>sam@acme.example</Email></UserDetails>"""

ME = b"""<User><UserId>900</UserId><UserName>aconex-gateway</UserName><OrganizationId>77</OrganizationId>
  <OrganizationName>Builder Co</OrganizationName></User>"""

GLOBAL_DIRECTORY = b"""<DirectorySearch><SearchResults>
  <Directory><UserId>601</UserId><FirstName>Alex</FirstName><LastName>Ng</LastName><OrganizationName>Steelworks Pty</OrganizationName></Directory>
</SearchResults></DirectorySearch>"""

COMPANY = b"""<Organization><OrganizationId>88</OrganizationId><OrganizationName>Acme Engineers</OrganizationName>
  <Address><City>Sydney</City></Address></Organization>"""

PROJECT_FIELDS = b"""<ProjectFields>
  <ProjectField><Id>11</Id><Label>Building</Label><Type>SINGLE_SELECT</Type><Enabled>true</Enabled></ProjectField>
  <ProjectField><Id>12</Id><Label>Level</Label><Type>TEXT</Type><Enabled>false</Enabled></ProjectField>
</ProjectFields>"""

MAILING_GROUPS = [{"groupId": "g1", "groupName": "Structural team", "isLocked": False,
                   "members": [{"userId": "501"}]}]

REGISTER = b"""<RegisterSearch TotalResults="2" CurrentPage="1" TotalPages="1"><SearchResults>
  <Document DocumentId="9001"><DocumentNumber>S-1100</DocumentNumber><Revision>B</Revision><Title>Level 1 slab plan</Title>
    <DocumentStatus>For Construction</DocumentStatus><RevisionDate>2026-10-20T00:00:00.000Z</RevisionDate>
    <Discipline>Structural</Discipline><DocumentType>Drawing</DocumentType><Filename>S-1100_B.pdf</Filename></Document>
  <Document DocumentId="9002"><DocumentNumber>S-1101</DocumentNumber><Revision>A</Revision><Title>Level 2 slab plan</Title>
    <DocumentStatus>For Review</DocumentStatus><RevisionDate>2026-10-21T00:00:00.000Z</RevisionDate>
    <Discipline>Structural</Discipline><DocumentType>Drawing</DocumentType><Filename>S-1101_A.pdf</Filename></Document>
</SearchResults></RegisterSearch>"""

HISTORY = b"""<RegisterSearch TotalResults="3"><SearchResults>
  <Document DocumentId="9001"><DocumentNumber>S-1100</DocumentNumber><Revision>B</Revision><RevisionDate>2026-10-20T00:00:00.000Z</RevisionDate></Document>
  <Document DocumentId="8001"><DocumentNumber>S-1100</DocumentNumber><Revision>A</Revision><RevisionDate>2026-09-01T00:00:00.000Z</RevisionDate></Document>
  <Document DocumentId="7001"><DocumentNumber>S-1100A</DocumentNumber><Revision>1</Revision><RevisionDate>2026-08-01T00:00:00.000Z</RevisionDate></Document>
</SearchResults></RegisterSearch>"""

# Live shape (2 Nov 2026): every field appears twice, once for registering
# (capitalised, e.g. Author) and once for searching (lower case, e.g. author).
SCHEMA = b"""<RegisterSchema><SearchSchemaFields>
  <SchemaField><Identifier>Author</Identifier><Name>Created By</Name></SchemaField>
  <SchemaField><Identifier>statusid</Identifier><Name>Status</Name><SchemaValues>
    <SchemaValue><Id>358</Id><Value>For Review</Value></SchemaValue>
    <SchemaValue><Id>359</Id><Value>For Construction</Value></SchemaValue>
  </SchemaValues></SchemaField>
  <SchemaField><Identifier>discipline</Identifier><Name>Discipline</Name><SchemaValues>
    <SchemaValue><Id>1</Id><Value>Structural</Value></SchemaValue>
  </SchemaValues></SchemaField>
  <SchemaField><Identifier>title</Identifier><Name>Title</Name></SchemaField>
  <SchemaField><Identifier>author</Identifier><Name>Created By</Name></SchemaField>
</SearchSchemaFields></RegisterSchema>"""

# Only found by searching the text on the drawings (content search).
DOOR_SCHEDULE = b"""<RegisterSearch TotalResults="1"><SearchResults>
  <Document DocumentId="9100"><DocumentNumber>A-2201</DocumentNumber><Revision>C</Revision><Title>Level 1 door schedule</Title>
    <DocumentStatus>For Construction</DocumentStatus><RevisionDate>2026-10-05T00:00:00.000Z</RevisionDate>
    <Discipline>Architectural</Discipline><DocumentType>Drawing</DocumentType><Filename>A-2201_C.pdf</Filename></Document>
</SearchResults></RegisterSearch>"""

NO_RESULTS = b"""<RegisterSearch TotalResults="0"><SearchResults/></RegisterSearch>"""

METADATA = b"""<Document DocumentId="9001"><DocumentNumber>S-1100</DocumentNumber><Revision>B</Revision>
  <Author>Sam Lee</Author><ReviewSource>WF-000020</ReviewSource><FileSize>2048000</FileSize></Document>"""

CURRENT_SET = b"""<CurrentSet><DocumentTypes><DocumentType>Drawing</DocumentType></DocumentTypes>
  <Statuses><Status>For Construction</Status></Statuses></CurrentSet>"""

EVENT_LOG = b"""<EventLog>
  <Event><Date>2026-10-20T01:00:00Z</Date><Type>Registered</Type><User>Sam Lee</User></Event>
  <Event><Date>2026-10-21T02:00:00Z</Date><Type>Transmitted</Type><User>Jo Park</User></Event>
</EventLog>"""

# Live shape (2 Nov 2026), with dates in milliseconds since 1970.
TRANSMITTALS = {"searchResults": [{"id": 9001, "transmittalDetails": [{
    "recvTransmittalNum": "TRANS-000042", "recvTransmittalUser": "Jo Park",
    "recvTransmittalDate": "1773616064000"}]}], "totalResultsCount": 1}

# Live shape (2 Nov 2026): groups, each holding saved searches whose filters
# sit in a search query alongside paging and plumbing settings.
SAVED_SEARCHES = b"""<SavedSearchGroups>
  <SavedSearchGroup id="savedSearchesCommonGroup" label="Standard Searches" type="2"><SavedSearches>
    <SavedSearch><Id>1</Id><Name>Approved</Name><SearchXmlString><SavedSearchObject><SearchQuery>
      <PageSize>25</PageSize><MaxResults>2147483647</MaxResults><DocStatusId>1</DocStatusId>
      <DocTypeId>-1</DocTypeId><Registered>true</Registered></SearchQuery></SavedSearchObject></SearchXmlString></SavedSearch>
  </SavedSearches></SavedSearchGroup>
  <SavedSearchGroup id="mySavedSearchesGroup" label="My Searches" type="1"/>
</SavedSearchGroups>"""

INTEGRITY = b"""<DocumentIntegrity>
  <Document><DocumentId>9001</DocumentId><LastModifiedDate>2026-10-30T03:00:00Z</LastModifiedDate></Document>
  <Document DocumentId="9002" LastModifiedDate="2026-10-31T03:00:00Z"/>
</DocumentIntegrity>"""


# A tiny but real PDF, as Aconex sends a register file (live: octet-stream,
# percent-encoded file name).
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
PDF_HEADERS = {"content-type": "application/octet-stream",
               "content-disposition": "attachment; filename=\"S-1100%20Rev%20B.pdf\"; filename*=UTF-8''S-1100%20Rev%20B.pdf"}


# Mail, in the live shapes seen on 2 Nov 2026. The company's own transmittal
# (m8) sits in both received and sent, as it does live.
def _mail_row(mail_id, number, sent, subject, name, org):
    return (f'<Mail MailId="{mail_id}"><MailNo>{number}</MailNo><SentDate>{sent}</SentDate>'
            f'<CorrespondenceType>Transmittal</CorrespondenceType><Subject>{subject}</Subject>'
            f'<FromUserDetails><Name>{name}</Name><OrganizationName>{org}</OrganizationName></FromUserDetails></Mail>')


INBOX = ('<MailSearch TotalResults="3" CurrentPage="1" TotalPages="1"><SearchResults>'
         + _mail_row("m8", "asmblr-TRANSMIT-000008", "2026-08-11T01:00:00.000Z", "Transmittal Update", "Lachie Barnett", "ASMBLR")
         + _mail_row("m2", "LSGP-TRANSMIT-000146", "2026-03-16T01:00:00.000Z", "FYI", "Michael Baysinger", "LVL Structures Group Pty Ltd")
         + _mail_row("m1", "LSGP-TRANSMIT-000143", "2026-03-15T01:00:00.000Z", "Warrs Project Example", "Michael Baysinger", "LVL Structures Group Pty Ltd")
         + "</SearchResults></MailSearch>").encode()
SENTBOX = ('<MailSearch TotalResults="2"><SearchResults>'
           + _mail_row("m8", "asmblr-TRANSMIT-000008", "2026-08-11T01:00:00.000Z", "Transmittal Update", "Lachie Barnett", "ASMBLR")
           + _mail_row("m7", "asmblr-TRANSMIT-000007", "2026-05-31T01:00:00.000Z", "Transmittal #7", "Rev Radar", "ASMBLR")
           + "</SearchResults></MailSearch>").encode()
NO_MAIL = b'<MailSearch TotalResults="0"><SearchResults/></MailSearch>'

MAIL_SCHEMA = b"""<SearchMailSchema>
  <SchemaField><Identifier>fromtradingname</Identifier><Name>From Organization Name</Name></SchemaField>
  <SchemaField><Identifier>corrtypeid</Identifier><Name>Mail Types</Name><SchemaValues>
    <SchemaValue><Id>23</Id><Value>Transmittal</Value></SchemaValue></SchemaValues></SchemaField>
  <SchemaField><Identifier>tostatusid</Identifier><Name>Status</Name><SchemaValues>
    <SchemaValue><Id>2</Id><Value>Outstanding</Value></SchemaValue>
    <SchemaValue><Id>5</Id><Value>Closed-Out</Value></SchemaValue></SchemaValues></SchemaField>
  <SchemaField><Identifier>reasonforissueid</Identifier><Name>Reason for Issue</Name><SchemaValues>
    <SchemaValue><Id>4</Id><Value>Issued for Information</Value></SchemaValue></SchemaValues></SchemaField>
</SearchMailSchema>"""

MAIL_DETAIL = b"""<Mail MailId="m1"><MailNo>LSGP-TRANSMIT-000143</MailNo>
  <CorrespondenceType>Transmittal</CorrespondenceType><Subject>Warrs Project Example</Subject>
  <SentDate>2026-03-15T01:00:00.000Z</SentDate><ReasonForIssue>Issued for Information</ReasonForIssue>
  <ThreadId>t1</ThreadId>
  <FromUserDetails><Name>Michael Baysinger</Name><OrganizationName>LVL Structures Group Pty Ltd</OrganizationName></FromUserDetails>
  <ToUsers>
    <Recipient><DistributionType>TO</DistributionType><Name>Lachie Barnett</Name><OrganizationName>ASMBLR</OrganizationName><UserId>u1</UserId></Recipient>
    <Recipient><DistributionType>CC</DistributionType><Name>Rev Radar</Name><OrganizationName>ASMBLR</OrganizationName><UserId>u2</UserId></Recipient>
  </ToUsers>
  <MailData>&lt;p&gt;Hi Lachie,&lt;/p&gt;&lt;p&gt;Precast drawings attached.&amp;nbsp;Thanks&lt;/p&gt;</MailData>
  <Attachments>
    <RegisteredDocumentAttachment attachmentId="a9"><DocumentId>9001</DocumentId><DocumentNo>S-1100</DocumentNo><Revision>B</Revision><Title>Level 1 slab plan</Title><FileName>S-1100_B.pdf</FileName></RegisteredDocumentAttachment>
    <LocalFileAttachment attachmentId="a1"><FileName>notes.pdf</FileName><FileSize>2048</FileSize></LocalFileAttachment>
  </Attachments>
</Mail>"""

MAIL_THREAD = b"""<MailThread>
  <Mail><MailNo>LSGP-TRANSMIT-000143</MailNo><Subject>Warrs Project Example</Subject><SentDate>2026-03-15T01:00:00.000Z</SentDate></Mail>
  <Mail><MailNo>LSGP-TRANSMIT-000146</MailNo><Subject>RE: Warrs Project Example</Subject><SentDate>2026-03-16T01:00:00.000Z</SentDate></Mail>
</MailThread>"""


BIG_MAIL = ("<Mail MailId=\"m3\"><MailNo>LSGP-TRANSMIT-000150</MailNo><MailStatus>Outstanding</MailStatus>"
            "<InRefToMailNo>LSGP-TRANSMIT-000143</InRefToMailNo><Attachments>"
            + "".join(f'<RegisteredDocumentAttachment attachmentId="x{i}"><DocumentNo>D-{i}</DocumentNo>'
                      f"<Status>Preliminary</Status></RegisteredDocumentAttachment>" for i in range(120))
            + "</Attachments></Mail>").encode()


class FakeAconex:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.logins = 0
        self.reject_next_token = False
        self.routes: dict[tuple[str, str], tuple] = {
            ("GET", "/projects"): (PROJECTS,),
            ("GET", "/projects/1001/directory"): (DIRECTORY,),
            ("GET", "/projects/1001/users/501"): (PERSON,),
            ("GET", "/users/501"): (PERSON,),
            ("GET", "/user"): (ME,),
            ("GET", "/directory"): (GLOBAL_DIRECTORY,),
            ("GET", "/organizations/88"): (COMPANY,),
            ("GET", "/projects/1001/projectField"): (PROJECT_FIELDS,),
            ("GET", "/mailinggroups/1001"): (MAILING_GROUPS,),
            ("GET", "/projects/1001/register"): (REGISTER,),
            ("GET", "/projects/1001/drawings"): (REGISTER,),
            ("GET", "/projects/1001/register/schema"): (SCHEMA,),
            ("GET", "/projects/1001/register/9001/metadata"): (METADATA,),
            ("GET", "/projects/1001/currentSet"): (CURRENT_SET,),
            ("GET", "/projects/1001/register/9001/eventlog"): (EVENT_LOG,),
            ("POST", "/projects/1001/register/search"): (TRANSMITTALS,),
            ("GET", "/projects/1001/documents/savedSearch"): (SAVED_SEARCHES,),
            ("GET", "/projects/1001/register/integrity"): (INTEGRITY,),
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            self.logins += 1
            return httpx.Response(200, json={"access_token": f"token-{self.logins}", "expires_in": 3600})
        path = request.url.path.removeprefix("/api")
        body = json.loads(request.content) if request.content else None
        self.calls.append({"method": request.method, "path": path,
                           "params": dict(request.url.params), "json": body})
        if self.reject_next_token:
            self.reject_next_token = False
            return httpx.Response(401, text="token expired")
        if request.method == "GET" and path == "/projects/1001/register/9001":
            return httpx.Response(200, content=PDF, headers=PDF_HEADERS)
        if request.method == "GET" and path == "/projects/1001/mail":
            box = request.url.params.get("mail_box")
            query = request.url.params.get("search_query", "")
            if "NOMATCH" in query:
                content = NO_MAIL
            elif "LSGP-TRANSMIT-000143" in query:
                content = INBOX if box == "Inbox" else NO_MAIL
            else:
                content = INBOX if box == "Inbox" else SENTBOX
            return httpx.Response(200, content=content, headers={"content-type": "application/xml"})
        mail_routes = {
            "/projects/1001/mail/schema/search": MAIL_SCHEMA,
            "/projects/1001/mail/m1": MAIL_DETAIL,
            "/projects/1001/mail/t1/thread": MAIL_THREAD,
            "/projects/1001/mail/m2/thread": MAIL_THREAD,
            "/projects/1001/mail/m3": BIG_MAIL,
            "/projects/1001/mail/savedSearches": SAVED_SEARCHES,
        }
        if request.method == "GET" and path in mail_routes:
            return httpx.Response(200, content=mail_routes[path], headers={"content-type": "application/xml"})
        if request.method == "GET" and path.startswith("/projects/1001/mail/m1/attachments/a1"):
            return httpx.Response(200, content=PDF, headers=PDF_HEADERS)
        query = request.url.params.get("search_query", "")
        if path == "/projects/1001/register" and ("1DG203" in query or "NOTHINGHERE" in query):
            found = "1DG203" in query and request.url.params.get("content_search") == "true"
            return httpx.Response(200, content=DOOR_SCHEDULE if found else NO_RESULTS,
                                  headers={"content-type": "application/xml"})
        if path == "/projects/1001/register" and request.url.params.get("show_document_history") == "true":
            return httpx.Response(200, content=HISTORY, headers={"content-type": "application/xml"})
        route = self.routes.get((request.method, path))
        if route is None:
            return httpx.Response(404, text="ENTITY_NOT_FOUND")
        content, kind = route[0], (route[1] if len(route) > 1 else None)
        if isinstance(content, (dict, list)):
            return httpx.Response(200, json=content)
        return httpx.Response(200, content=content,
                              headers={"content-type": kind or "application/xml"})

    def client(self, connected: bool = True) -> AconexClient:
        settings = Settings("client-id", "client-secret") if connected else Settings()
        return AconexClient(settings, transport=httpx.MockTransport(self.handler))
