# Requirements Document

## Introduction

GridLock is a coordination radar for electric utility capital planners. Neighboring utilities plan capital projects (substations, transmission lines, generation) years in advance without visibility into each other's plans. GridLock ingests the public capital plans of two or more utilities (PDF or spreadsheet), uses a Large Language Model to extract every project into a common schema, geocodes and stores each project, and flags project pairs that are close in both space and time. For each flagged pair, GridLock generates a short coordination brief that a planner can forward to a neighboring utility (for example, suggesting a shared crane crew for two nearby breaker replacements in the same quarter).

The product centers on a human-in-the-loop workflow: planners review low-confidence extractions, tune matching thresholds, inspect why a pair was flagged, and export coordination briefs. Every project links back to its source document page for verification.

This document scopes an MVP (must-ship for the hackathon demo) and a set of Stretch requirements. Requirements are tagged **[MVP]** or **[Stretch]** in their headings.

## Glossary

- **GridLock**: The overall system comprising the ingestion pipeline, data store, matching engine, brief generator, and web UI.
- **System**: A synonym for GridLock, referring to the overall system when a specific component is not being singled out.
- **Ingestion_Service**: The GridLock component that accepts uploaded utility plans and initiates processing.
- **Extraction_Service**: The GridLock component that uses the LLM to convert source documents into structured Project records.
- **LLM**: The Large Language Model (Gemini) used for extraction and brief generation.
- **Geocoding_Service**: The GridLock component that converts substation names, town names, or county names into geographic coordinates.
- **Data_Store**: The PostgreSQL database (with the PostGIS extension) that persists Project records and supports spatial and temporal queries.
- **Matching_Engine**: The GridLock component that identifies and scores candidate coordination pairs.
- **Brief_Generator**: The GridLock component that uses the LLM to produce a coordination brief for a flagged pair.
- **Web_UI**: The GridLock browser application providing the map, timeline, threshold controls, why-flagged panel, and review screen.
- **Review_Screen**: The Web_UI view where a Planner inspects and edits extracted projects.
- **Export_Service**: The GridLock component that produces downloadable files of coordination briefs.
- **Planner**: A human utility capital planner who uses GridLock to review extractions, tune thresholds, and export briefs.
- **Project**: A single planned capital work item extracted from a source document. Fields: id, utility, state, name, type, voltage_kv, geom, start_date, end_date, confidence, source_url, source_page, raw_excerpt, reviewed.
- **Project_Type**: One of the enumerated categories: substation, transmission line, generation.
- **Coordination_Pair**: A pair of Projects from two different utilities that satisfy the spatial and temporal matching criteria.
- **Coordination_Brief**: A short natural-language recommendation describing a Coordination_Pair and a proposed coordination opportunity.
- **Confidence**: A numeric score between 0.0 and 1.0 the Extraction_Service assigns to each extracted Project, indicating extraction reliability.
- **Confidence_Threshold**: The configurable Confidence value below which a Project is flagged for human review. Default value is 0.7.
- **Distance_Radius**: The configurable maximum great-circle distance, in miles, within which two Projects are considered spatially close. Default value is 25 miles.
- **Date_Padding**: The configurable number of days added to each side of a Project date range before testing for temporal overlap. Default value is 30 days.
- **Overlap_Days**: The number of calendar days two padded Project date ranges share.
- **Approximate_Location**: A Project geom derived from a county center point rather than a specific substation or town, marked as approximate.

## Requirements

### Requirement 1: Plan Ingestion [MVP]

**User Story:** As a Planner, I want to upload two or more utilities' public capital plans, so that GridLock can analyze them for coordination opportunities.

#### Acceptance Criteria

1. WHEN a file in PDF, XLSX, or CSV format is submitted to the POST /ingest endpoint, THE Ingestion_Service SHALL accept the file and return an acknowledgment containing a unique identifier for the ingested plan.
2. WHEN a file is submitted with source utility and source_url metadata, THE Ingestion_Service SHALL record the source utility and source_url and return a confirmation that both values were stored.
3. IF a submitted file is in a format other than PDF, XLSX, or CSV, THEN THE Ingestion_Service SHALL reject the submission and return an error indicating the submitted format is unsupported and identifying the detected format.
4. IF a submitted file exceeds 50 MB in size, THEN THE Ingestion_Service SHALL reject the submission and return an error indicating the file exceeds the 50 MB maximum size limit.
5. THE Ingestion_Service SHALL support a dataset containing between 2 and 50 distinct utilities, inclusive.
6. IF a submitted file is in a supported format but is corrupt or unreadable, THEN THE Ingestion_Service SHALL reject the submission, return an error indicating the file could not be read, and retain no partial record of the plan.
7. IF a submission is missing the required source utility metadata or the required source_url metadata, THEN THE Ingestion_Service SHALL reject the submission, return an error identifying which required metadata field is missing, and retain no partial record of the plan.

### Requirement 2: LLM Extraction into Common Schema [MVP]

**User Story:** As a Planner, I want each source plan converted into a common project schema, so that projects from different utilities can be compared consistently.

#### Acceptance Criteria

1. WHEN the Ingestion_Service accepts a document, THE Extraction_Service SHALL use the LLM to extract each identified project in the document into a separate Project record.
2. THE Extraction_Service SHALL consider for population, independent of whether a Project record already exists, the following fields for each Project: name, utility, type, voltage_kv, location reference, start_date, end_date, source_page, and raw_excerpt.
3. IF a field value for a Project cannot be determined from the source document, THEN THE Extraction_Service SHALL set that field to an empty value and still create the Project record with all remaining determinable fields populated.
4. THE Extraction_Service SHALL assign each Project a type value from the enumeration substation, transmission line, or generation.
5. IF the LLM cannot classify a Project into one of the enumerated type values, THEN THE Extraction_Service SHALL set the type field to an empty value and retain the Project record.
6. WHEN the source document specifies a voltage for a Project, THE Extraction_Service SHALL record the voltage as a numeric value in kilovolts, within the range 0.1 to 2000 kV, in the voltage_kv field.
7. THE Extraction_Service SHALL record in the source_page field the page number, between 1 and the total page count of the source document, from which each Project was extracted.
8. THE Extraction_Service SHALL record in the raw_excerpt field the verbatim source text, up to a maximum of 2000 characters, from which each Project was extracted.
9. IF the LLM extraction fails for the document, THEN THE Extraction_Service SHALL create no Project records for that document and SHALL return a failure indication to the caller identifying that extraction failed.

### Requirement 3: Extraction Confidence [MVP]

**User Story:** As a Planner, I want each extracted project to carry a confidence score, so that I can focus my review on uncertain extractions.

#### Acceptance Criteria

1. WHEN the Extraction_Service extracts a Project, THE Extraction_Service SHALL assign a Confidence value between 0.0 and 1.0 to that Project.
2. WHEN the Extraction_Service creates a Project, THE Extraction_Service SHALL set the reviewed flag of that Project to false.
3. WHEN a Project has a Confidence value equal to or below the Confidence_Threshold, THE Web_UI SHALL visually distinguish that Project as requiring review.

### Requirement 4: Geocoding with Fallbacks [MVP]

**User Story:** As a Planner, I want project locations resolved to map coordinates even when only a name or county is given, so that every project can appear on the map.

#### Acceptance Criteria

1. WHEN a Project provides a substation name or town name, THE Geocoding_Service SHALL resolve the name to a latitude/longitude coordinate and store it in the geom field as an SRID 4326 geography point.
2. WHERE a Project provides only a county-level location reference, THE Geocoding_Service SHALL set the geom field to the county center coordinate as an SRID 4326 geography point and mark the location as an Approximate_Location.
3. IF a geocoding resolution attempt does not complete within 10 seconds, THEN THE Geocoding_Service SHALL treat the attempt as failed and retry the resolution up to a maximum of 3 attempts.
4. IF all 3 resolution attempts fail, THEN THE Geocoding_Service SHALL mark the Project as requiring review and leave the geom field unset.
5. IF a resolution returns more than one candidate match, THEN THE Geocoding_Service SHALL treat the location as unresolved, mark the Project as requiring review, and leave the geom field unset.
6. WHEN the source provides a date value with only quarter or year precision, THE Geocoding_Service SHALL preserve the original quarter or year precision without inferring a more specific date.

### Requirement 5: Project Storage [MVP]

**User Story:** As a Planner, I want extracted projects stored in a database that supports spatial and temporal queries, so that GridLock can compute distances and time overlaps.

#### Acceptance Criteria

1. WHEN a Project is extracted and geocoded, THE Data_Store SHALL persist the Project with the fields id, utility, state, name, type, voltage_kv, geom, start_date, end_date, confidence, source_url, source_page, raw_excerpt, and reviewed.
2. THE Data_Store SHALL store the geom field as a PostGIS geography point with SRID 4326.
3. THE Data_Store SHALL store the start_date and end_date such that the Matching_Engine can evaluate date-range overlap.
4. WHEN a Planner requests the GET /projects endpoint, THE Data_Store SHALL return the stored Projects.

### Requirement 6: Overlap Matching [MVP]

**User Story:** As a Planner, I want GridLock to flag pairs of projects that are close in space and time, so that I can identify coordination opportunities.

#### Acceptance Criteria

1. WHEN a Planner requests the GET /overlaps endpoint, THE Matching_Engine SHALL return the set of Coordination_Pairs derived from the stored Projects.
2. THE Matching_Engine SHALL include a Coordination_Pair only when the two Projects belong to different utilities.
3. THE Matching_Engine SHALL include a Coordination_Pair only when the two Projects' geom points are within the Distance_Radius of each other.
4. THE Matching_Engine SHALL include a Coordination_Pair only when the two Projects' date ranges, each extended by the Date_Padding, overlap.
5. WHEN the GET /overlaps request supplies a radius parameter, THE Matching_Engine SHALL use the supplied value as the Distance_Radius; otherwise THE Matching_Engine SHALL use a default Distance_Radius of 25 miles.
6. WHEN the GET /overlaps request supplies a pad parameter, THE Matching_Engine SHALL use the supplied value as the Date_Padding; otherwise THE Matching_Engine SHALL use a default Date_Padding of 30 days.
7. IF the GET /overlaps request supplies one or more of the radius or pad parameters that are negative or non-numeric, THEN THE Matching_Engine SHALL reject the request and return a single error response identifying every invalid parameter supplied.
8. THE Matching_Engine SHALL exclude any Project whose geom field is unset from all Coordination_Pairs.
9. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute the distance between the two Projects in miles.
10. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute the Overlap_Days shared by the two padded date ranges.

### Requirement 7: Pair Scoring [MVP]

**User Story:** As a Planner, I want each flagged pair scored on multiple factors, so that I can prioritize the strongest coordination opportunities.

#### Acceptance Criteria

1. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute a distance score in the range 0.0 to 1.0, where the score equals 1.0 when the distance between the two Projects is 0 and decreases monotonically to 0.0 as the distance increases to or beyond the Distance_Radius.
2. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute an overlap score in the range 0.0 to 1.0, where the score equals 0.0 when Overlap_Days is 0 or negative and increases monotonically to 1.0 as Overlap_Days increases to or beyond a configured maximum overlap-days threshold.
3. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute a type-similarity score of 1.0 when the two Projects' type values are equal and 0.0 when they differ.
4. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute a voltage-similarity score of 1.0 when the two Projects' voltage_kv values are equal and, when they differ, a value in the range 0.0 to 1.0 that decreases monotonically as the absolute difference between the two voltage_kv values increases.
5. FOR EACH Coordination_Pair, THE Matching_Engine SHALL compute a composite score in the range 0.0 to 1.0 by combining the distance, overlap, type-similarity, and voltage-similarity scores.
6. IF any Project attribute required to compute a score factor is missing or invalid, THEN THE Matching_Engine SHALL set the affected factor score to 0.0 and mark that factor as indeterminate for the Coordination_Pair.
7. FOR EACH Coordination_Pair, THE Matching_Engine SHALL make each individual score factor value and the composite score available to the Web_UI for display.

### Requirement 8: Coordination Brief Generation [MVP]

**User Story:** As a Planner, I want a short written recommendation for each flagged pair, so that I can forward a coordination suggestion to a neighboring utility.

#### Acceptance Criteria

1. WHEN a Planner submits a POST /overlaps/{id}/brief request for an existing Coordination_Pair, THE Brief_Generator SHALL use the LLM to produce a Coordination_Brief for that pair within 30 seconds.
2. THE Brief_Generator SHALL produce each Coordination_Brief with a length of 1 to 4 sentences and no more than 600 characters, formatted for forwarding to a neighboring utility.
3. THE Brief_Generator SHALL include in the Coordination_Brief the two Projects' types, their distance in miles, and their overlapping time window.
4. THE Brief_Generator SHALL include in the Coordination_Brief a proposed coordination opportunity for the pair.
5. IF the requested Coordination_Pair does not exist, THEN THE Brief_Generator SHALL return an error message indicating the pair was not found and SHALL NOT produce a Coordination_Brief.
6. IF the LLM does not return a response within 30 seconds, THEN THE Brief_Generator SHALL return an error message indicating the generation timed out and SHALL NOT return a partial Coordination_Brief.
7. IF the Brief_Generator cannot produce a Coordination_Brief for an existing requested pair for any other reason, THEN THE Brief_Generator SHALL return an error message identifying the failure and SHALL retain the Coordination_Pair unchanged.

### Requirement 9: Map and Timeline Display [MVP]

**User Story:** As a Planner, I want to see all projects on a map and timeline with flagged pairs highlighted, so that I can visually explore coordination opportunities.

#### Acceptance Criteria

1. THE Web_UI SHALL display each stored Project as a marker on a map at the Project's geom coordinates.
2. THE Web_UI SHALL display each Project on a timeline positioned by the Project's start_date and end_date.
3. WHERE a Project is part of a Coordination_Pair, THE Web_UI SHALL visually highlight that Project on the map.
4. WHERE a Project location is an Approximate_Location, THE Web_UI SHALL visually distinguish that Project marker as approximate.

### Requirement 10: Threshold Controls [MVP]

**User Story:** As a Planner, I want sliders to adjust the distance and time thresholds, so that I can tune which pairs GridLock flags and watch the results change.

#### Acceptance Criteria

1. THE Web_UI SHALL provide a control that sets the Distance_Radius used for matching.
2. THE Web_UI SHALL provide a control that sets the Date_Padding used for matching.
3. WHEN a Planner changes the Distance_Radius control, THE Web_UI SHALL update the displayed Coordination_Pairs to reflect the new Distance_Radius.
4. WHEN a Planner changes the Date_Padding control, THE Web_UI SHALL update the displayed Coordination_Pairs to reflect the new Date_Padding.

### Requirement 11: Why-Flagged Panel [MVP]

**User Story:** As a Planner, I want to see why a pair was flagged and view the two projects side by side, so that I can judge whether the coordination opportunity is real.

#### Acceptance Criteria

1. WHEN a Planner selects a Coordination_Pair, THE Web_UI SHALL display the two Projects side by side.
2. WHEN a Planner selects a Coordination_Pair, THE Web_UI SHALL display the distance in miles, the Overlap_Days, and the individual score factors for that pair.
3. WHERE a Coordination_Brief exists for the selected Coordination_Pair, THE Web_UI SHALL display the Coordination_Brief.
4. WHERE no Coordination_Brief exists for the selected Coordination_Pair, THE Web_UI SHALL display an explicit indicator that no Coordination_Brief exists.

### Requirement 12: Source-Page Linking [MVP]

**User Story:** As a Planner, I want each project to link to its source document page, so that I can verify the extraction against the original plan.

#### Acceptance Criteria

1. THE Web_UI SHALL display for each Project a link constructed from the Project's source_url and source_page.
2. WHEN a Planner activates a Project's source link, THE Web_UI SHALL open the source document at the Project's source_page in a new browser tab or window, preserving the current Web_UI view.

### Requirement 13: Human Review and Edit Workflow [MVP]

**User Story:** As a Planner, I want to review and correct low-confidence extractions, so that the flagged pairs are based on trustworthy data.

#### Acceptance Criteria

1. WHEN a Project has a Confidence value equal to or below the Confidence_Threshold, THE Review_Screen SHALL visually distinguish that Project from Projects with Confidence above the Confidence_Threshold.
2. WHEN a Planner submits a PATCH /projects/{id} request with valid field values for an existing Project, THE Data_Store SHALL persist the edited field values and THE System SHALL return the updated Project representation within 2 seconds.
3. WHEN a Planner submits a PATCH /projects/{id} request that sets the reviewed field to true for an existing Project, THE Data_Store SHALL persist reviewed as true and THE System SHALL return the updated Project representation.
4. WHEN a Planner submits a PATCH /projects/{id} request that modifies the geom field or any date field of an existing Project that has already been matched, THE Matching_Engine SHALL immediately re-run overlap matching for that Project using the edited geom and date values and SHALL update or invalidate the affected existing Coordination_Pairs to reflect the edited values.
5. IF a PATCH /projects/{id} request contains one or more field values that fail validation, THEN THE System SHALL reject the request, persist no changes to the target Project, and return an error response indicating which field values were invalid.
6. IF a PATCH /projects/{id} request references a Project id that does not exist, THEN THE System SHALL persist no changes and return a not-found error response indicating the Project id was not found.

### Requirement 14: Coordination Brief Export [Stretch]

**User Story:** As a Planner, I want to export coordination briefs to a file, so that I can share them outside GridLock with neighboring utilities.

#### Acceptance Criteria

1. WHEN a Planner requests the GET /export endpoint in CSV format, THE Export_Service SHALL produce a CSV file containing the Coordination_Pairs and their Coordination_Briefs.
2. WHEN a Planner requests the GET /export endpoint in PDF format, THE Export_Service SHALL produce a PDF file containing the Coordination_Pairs and their Coordination_Briefs.
3. IF an export record is missing either of the two Projects' utilities, THEN THE Export_Service SHALL reject the export as invalid and SHALL NOT produce the export with a missing utility.
4. THE Export_Service SHALL include in each exported record the two Projects' utilities, names, distance in miles, and overlapping time window.

### Requirement 15: Additional Utilities [Stretch]

**User Story:** As a Planner, I want to compare more than two utilities at once, so that I can find coordination opportunities across a larger region.

#### Acceptance Criteria

1. THE Ingestion_Service SHALL support ingesting plans from three or more distinct utilities within a single dataset.
2. WHEN a dataset contains three or more utilities, THE Matching_Engine SHALL evaluate Coordination_Pairs across every combination of two different utilities.

### Requirement 16: Deployment and Domain [Stretch]

**User Story:** As a Planner, I want GridLock hosted at a public web address, so that I can access it and demonstrate it without local setup.

#### Acceptance Criteria

1. THE GridLock system SHALL be deployable to a cloud host reachable over the public internet.
2. THE Web_UI SHALL be reachable through a registered public domain name.

### Requirement 17: Transmission Line Geometry [Stretch]

**User Story:** As a Planner, I want transmission line projects represented by their real routes, so that distance matching for lines reflects the actual corridor.

#### Acceptance Criteria

1. WHERE a Project has the type transmission line, THE Geocoding_Service SHALL represent the Project geometry using its two endpoint substations.
2. WHEN evaluating a Coordination_Pair involving a transmission line Project, THE Matching_Engine SHALL measure distance against the transmission line geometry.
