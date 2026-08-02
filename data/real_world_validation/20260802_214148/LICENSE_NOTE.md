# License note for this directory

Derived from the PerHeart Pilot Dataset (Kolakowski et al., Data 2026, 11(5):106,
https://doi.org/10.5281/zenodo.17143199).

Zenodo's structured record metadata declares CC-BY 4.0. The dataset's own bundled
`load_dataset.py` (authors' own file) states CC BY-NC-SA 4.0 (Attribution-NonCommercial-
ShareAlike) in its footer -- these two statements disagree, and this was not resolved with the
authors before this analysis. Treating the more restrictive reading as binding:

- This directory's contents (model outputs keyed to the dataset's own existing pseudonymous
  user_id 1-27 -- no new identifying information is introduced) are themselves distributed under
  CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/), consistent with the
  ShareAlike clause under either license reading.
- Non-commercial academic/research use (this paper) is permitted under both readings.
- The raw dataset files themselves are NOT committed to this repository -- see data/raw/ (gitignored)
  and docs/data_provenance.md's "never real patient data in git" rule.
