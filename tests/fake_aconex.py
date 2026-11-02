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

RELATIONSHIP_CHANGES = [{"documentId": "9001", "relatedDocumentId": "9002", "action": "CREATED"}]

LOGO = b"\x89PNG\r\n\x1a\nfake-logo"


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
            ("GET", "/project/logo"): (LOGO, "image/png"),
            ("GET", "/organization/logo"): (LOGO, "image/png"),
            ("GET", "/projects/1001/register"): (REGISTER,),
            ("GET", "/projects/1001/drawings"): (REGISTER,),
            ("GET", "/projects/1001/register/schema"): (SCHEMA,),
            ("GET", "/projects/1001/register/9001/metadata"): (METADATA,),
            ("GET", "/projects/1001/currentSet"): (CURRENT_SET,),
            ("GET", "/projects/1001/register/9001/eventlog"): (EVENT_LOG,),
            ("POST", "/projects/1001/register/search"): (TRANSMITTALS,),
            ("GET", "/projects/1001/documents/savedSearch"): (SAVED_SEARCHES,),
            ("GET", "/projects/1001/register/integrity"): (INTEGRITY,),
            ("GET", "/document-relationships/projects/1001/transactions"): (RELATIONSHIP_CHANGES,),
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
