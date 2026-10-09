# Donor notebooks

Drop the two legacy notebooks here for reference:

* `Icesat_download.ipynb` — CMR discovery + `icesat2.atl03sp(...)` photon workflow.
  Logic reused in `src/kakhovka_altimetry/discovery.py`. The ATL03 photon path
  itself is **out of scope for V1** but kept here for the second-level validation
  (ATL03 vs ATL13 surface reconstruction) described in the project README.
* the EGG2015 notebook — samples the quasigeoid at point locations and computes
  `orthometric_height = height − geoid_height`. Logic reused, with ATL13
  `ht_water_surf` as the input height, in `src/kakhovka_altimetry/vertical.py`.

These files are git-ignored (`notebooks/_donor/*.ipynb`) — they are inputs, not
part of the pipeline.
