#!/usr/bin/env python3
"""Create reference_guide.odt with plain text reference guide content."""
import zipfile
import os

CONTENT_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
  <office:body>
    <office:text>
      <text:p text:style-name="Standard">API Reference Guide</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">This document provides a comprehensive reference for the company REST API. All endpoints require authentication unless otherwise noted. The base URL for all API calls is https://api.example.com/v2.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Authentication</text:p>
      <text:p text:style-name="Standard">All API requests must include a valid Bearer token in the Authorization header. Tokens are obtained via the OAuth 2.0 client credentials flow. Each token is valid for 3600 seconds. To refresh a token, call the /auth/refresh endpoint with your refresh token.</text:p>
      <text:p text:style-name="Standard">Example: Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Endpoints</text:p>
      <text:p text:style-name="Standard">GET /users - Returns a paginated list of all users. Supports query parameters: page, limit, sort, filter. Default limit is 25 results per page.</text:p>
      <text:p text:style-name="Standard">POST /users - Creates a new user account. Required fields: email, name, role. Optional fields: department, phone, timezone.</text:p>
      <text:p text:style-name="Standard">GET /users/{id} - Returns details for a specific user by their unique identifier.</text:p>
      <text:p text:style-name="Standard">PUT /users/{id} - Updates an existing user record. All fields are optional; only provided fields will be updated.</text:p>
      <text:p text:style-name="Standard">DELETE /users/{id} - Soft-deletes a user account. The account can be restored within 30 days.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Error Codes</text:p>
      <text:p text:style-name="Standard">400 Bad Request - The request body or parameters are malformed. Check the error message for details on which field is invalid.</text:p>
      <text:p text:style-name="Standard">401 Unauthorized - The Bearer token is missing, expired, or invalid. Obtain a new token and retry.</text:p>
      <text:p text:style-name="Standard">403 Forbidden - The authenticated user does not have permission to access the requested resource.</text:p>
      <text:p text:style-name="Standard">404 Not Found - The requested resource does not exist or has been deleted.</text:p>
      <text:p text:style-name="Standard">429 Too Many Requests - Rate limit exceeded. See the Rate Limits section for details.</text:p>
      <text:p text:style-name="Standard">500 Internal Server Error - An unexpected error occurred on the server. Contact support if this persists.</text:p>
      <text:p text:style-name="Standard"></text:p>
      <text:p text:style-name="Standard">Rate Limits</text:p>
      <text:p text:style-name="Standard">All API endpoints are subject to rate limiting. The default rate limit is 1000 requests per minute for standard accounts and 5000 requests per minute for enterprise accounts. Rate limit headers are included in every response: X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset.</text:p>
      <text:p text:style-name="Standard">When the rate limit is exceeded, the API returns a 429 status code with a Retry-After header indicating when the client may retry.</text:p>
    </office:text>
  </office:body>
</office:document-content>'''

META_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
  office:version="1.2">
  <office:meta>
    <meta:generator>Python ODT Generator</meta:generator>
  </office:meta>
</office:document-meta>'''

STYLES_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.2">
</office:document-styles>'''

MANIFEST_XML = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
  <manifest:file-entry manifest:media-type="application/vnd.oasis.opendocument.text" manifest:full-path="/"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="meta.xml"/>
  <manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>
</manifest:manifest>'''

MIMETYPE = 'application/vnd.oasis.opendocument.text'

out_path = '/home/user/Documents/reference_guide.odt'
os.makedirs(os.path.dirname(out_path), exist_ok=True)

with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('mimetype', MIMETYPE, compress_type=zipfile.ZIP_STORED)
    zf.writestr('META-INF/manifest.xml', MANIFEST_XML)
    zf.writestr('content.xml', CONTENT_XML)
    zf.writestr('meta.xml', META_XML)
    zf.writestr('styles.xml', STYLES_XML)

print(f"Created {out_path}")
