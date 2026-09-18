# RM-12A public fixture checkpoint

The corrected rate/minimum-HTML fixtures ran against A-runtime-01 production.
One test passed and three failed. The new shadow case reproduces missing monthly
processing-cap retention, which remains assigned to the source implementer.

The other failures expose oversized test input: repeated long words exceed the
existing 50000-character page-content ceiling before sentence/token preparation.
Use short eighty-sentence input for the sentence oracle and separate token-dense
input below that ceiling for the source-token oracle. Do not relax the required
eighty delivered sentences or the source-token boundary assertions.
