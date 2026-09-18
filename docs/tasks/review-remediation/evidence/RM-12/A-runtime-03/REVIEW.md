# Independent Astra review: correction required

Reviewer rm03_security_rereview verified all ten source hashes and the increment.
The allowance resolver now avoids lookup for complete caps, but reserve still
looks up the current plan before consulting an existing operation. The public
saved-preload regression reaches that path and fails. Preserve canonical payload
and accounting-mode validation while making existing replay independent of that
lookup. Other prior source and fixture findings are closed at this checkpoint.
The reviewer did not run runtime checks or edit source.
