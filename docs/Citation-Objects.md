# Citation Objects

Three citation objects cover peira. Each one serves a different stage of
the project, and they are built to agree with each other.

## The three objects

1. CITATION.cff and CITATION.bib. Machine readable citation metadata that
ships in the repo. These exist today and are the ones to use now.

2. The paper. A written report on the benchmark and its first results,
posted on arXiv and carrying a DOI. It does not exist yet because there
are no results to report.

3. The Zenodo dataset record. An archived copy of the public dataset with
its own DOI. Zenodo issues a concept DOI that always points at the latest
release, plus a per version DOI for each release so any exact dataset
version can be cited on its own. It does not exist yet. It ships with the
v1 results.

## The pre-commitment

When the paper ships, the BibTeX entry gets the arXiv ID and the DOI
filled in. When the Zenodo record ships, the BibTeX and CFF entries get
the dataset DOI added, and the concept DOI stays stable across releases
while each dataset release gets its own version DOI. Title, author, and
version stay identical across all three objects.

## How to cite peira today

Use the CITATION.bib entry at the repo root. It pins the repository, the
version, and the release date. That entry is the full citation until the
paper exists.

## How to cite peira after publication

Cite the paper for the methodology and the results. Cite the Zenodo per
version DOI for the exact dataset those results were computed on. Use
separate BibTeX entries with distinct citation keys, one for the paper
and one for the dataset version, so each work can be cited independently.
