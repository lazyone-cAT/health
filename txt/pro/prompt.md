# PROJECT PROMPT: Hospital Operations Command Center (Discord-Style RBAC)

## 1. OBJECTIVE
Build a prototype web application (using Python, Streamlit, Pandas, and SQLite) that replaces manual, time-consuming hospital reporting with a single, reconciled, real-time operational dashboard. 

The app must solve the problem of fragmented data (HIS, Lab Logs, Manual Bed Sheets) and provide role-based access exactly like **Discord servers**, where each "Floor" acts as a separate server with specific roles and permissions.

## 2. THE CORE PROBLEM (Context)
Currently, 3 inconsistent data files exist:
- File A: HIS Admissions/Discharge (System data).
- File B: Lab Order-to-Result Turnaround (System data).
- File C: Manually maintained Bed Occupancy Sheet (Excel).
Operations leads waste hours manually compiling these. Reconciliation is done arbitrarily.

## 3. THE ARCHITECTURE (Discord Analogy)
Treat the hospital building as having **3 Floors (Servers)**:
- **Floor 1**: General Ward (Server 1)
- **Floor 2**: ICU / Critical Care (Server 2)
- **Floor 3**: Maternity / Surgery (Server 3)

**Role Hierarchy (Permissions Matrix):**
1. **Patient (Guest)**: Read-Only. Can only see their own name, bed number, and lab results. No edit buttons visible.
2. **Nurse (Senior Member)**: Assigned to 1 floor. Can ONLY edit the **Bed Collection** (mark beds Clean/Dirty/Occupied) and log cleaning tasks. Cannot touch clinical data.
3. **Doctor (Special Member)**: Assigned to 1 or more floors. Can ONLY edit the **HIS/Clinical Collection** (write Discharge Orders, Diagnoses, Prescriptions). Updates the `Time_Left` clock for discharge.
4. **Head Nurse (Moderator)**: Assigned to 1 floor. Has all Nurse powers, PLUS can override minor conflicts on their specific floor and check-in/out staff on that floor. Cannot see other floors.
5. **Super Admin (Server Owner)**: **Global "Eye" access**. Can see ALL floors simultaneously (Floor 1, 2, 3 side-by-side). Can override ANY conflict across the entire hospital. Can assign roles to users.

## 4. DATA RECONCILIATION ENGINE (The Brain)
Write a Python backend that ingests the 3 sample files and performs a FULL OUTER JOIN based on `Patient_ID` and `Bed_ID`. **Do not silently drop mismatches.**

**Explicit Reconciliation Rules to code:**
- **Rule 1 (Bed Status)**: If HIS and Manual Sheet disagree on occupancy, **the Manual Sheet wins** (nurses reflect physical reality).
- **Rule 2 (Lab TAT)**: If HIS and Lab Log disagree on result time, **the Lab Log wins** (lab is source of truth).
- **Rule 3 (Discharge)**: If HIS has a `Discharge_Order_Time`, calculate `Time_Left = Discharge_Order_Time - NOW()`. Flag as "Overdue" if negative.
- **Rule 4 (Conflict Flag)**: Any disagreement between sources must be logged into a separate `Conflict_Log` table with the timestamp and the rule applied.

## 5. DATABASE SCHEMA (SQLite)
Generate SQL `CREATE TABLE` statements for the following interconnected tables:
- `FLOOR` (Floor_ID, Floor_Number, Ward_Name)
- `ROOM` (Room_ID, Floor_ID, Room_Number)
- `BED` (Bed_ID, Room_ID, Current_Status)  *Inherits Floor_ID via Room.*
- `PATIENT` (Patient_ID, Name, DOB)
- `ADMISSION` (Admission_ID, Patient_ID, Bed_ID, Admit_Time, Discharge_Ordered_Time)
- `USER` (User_ID, Username, Password_Hash, Role_ID, Default_Floor_ID, is_global_admin)
- `ROLE` (Role_ID, Role_Name, Priority_Level) *Populate with Patient, Nurse, Doctor, Head_Nurse, Super_Admin.*
- `USER_FLOOR_ACCESS` (Many-to-Many mapping to allow Doctors/Admins to access multiple floors).
- `CONFLICT_LOG` (Log_ID, Patient_ID, Source_1_Value, Source_2_Value, Resolution_Rule_Applied, Resolved_By_User_ID).
- `ATTENDANCE` (Check-in/out for Staff).

## 6. REQUIRED UI PAGES (Streamlit)

**Page 1: Login**
- Username/Password login.
- Determines Role and assigned Floors.

**Page 2: Server Switcher (Top Bar)**
- If user is Super Admin: Show a dropdown with [Floor 1, Floor 2, Floor 3, **Global HQ (All Floors)**].
- If user is Nurse/Head Nurse: Show a dropdown with only their assigned floor(s).
- Switch floors seamlessly (like changing Discord servers).

**Page 3: The Dashboard (Based on Selected Server)**
- **KPI Cards**: Show `Bed Occupancy %`, `Avg Lab TAT`, `Patients Overdue for Discharge`, `Active Conflicts`.
- *Admin View*: If "Global HQ" is selected, display these KPIs in 3 side-by-side columns (one for each floor) for comparison.
- **Bed Heatmap**: A visual grid showing occupied/clean/dirty beds for the selected floor.

**Page 4: Master Reconciliation Table**
- Show the single source of truth (merged data).
- **Crucial Feature**: Add an orange `⚠️ Conflict` badge next to rows that exist in the `CONFLICT_LOG`. 
- Clicking the badge opens a popup explaining exactly which sources disagreed and how the system resolved it (e.g., *"Manual Sheet won vs HIS"*).

**Page 5: Admin Override Panel**
- Only visible to Head Nurse and Super Admin.
- Allows them to manually pick which source to trust (e.g., "Force Trust HIS") for a specific conflicting row.
- Logs who made the override and why.

**Page 6: Honesty Page (Gaps)**
- Explicitly list: *"Tool covers Inpatient beds and Lab TAT. Does NOT cover Outpatient clinics. Does NOT predict future capacity."*

## 7. THE "EYE" FEATURE (Super Admin Specific)
When the Super Admin selects "Global HQ":
- Show a hospital-wide summary.
- Allow them to click on any conflict from Floor 2 and resolve it remotely, even if they are physically assigned to Floor 1.
- Show a list of currently checked-in staff across ALL floors in one unified list.

## 8. TECHNICAL CONSTRAINTS
- **Framework**: Streamlit (frontend) and Python (Pandas for ETL).
- **Database**: SQLite (lightweight, single file).
- **User Assumption**: The user is competent at their job but NOT technical. Hide all code. Use plain English labels like "Resolve Conflict" instead of "API POST."
- **Inputs**: Provide dummy code to generate 3 synthetic CSV files (HIS, Lab, Manual) with deliberate inconsistencies for testing.
- **Outputs**: 
  1. A `master_reconciled_view` DataFrame.
  2. A `conflict_log` DataFrame.
  3. Exported KPIs (JSON or CSV).
- **Security**: Implement row-level security. Ensure a Nurse on Floor 1 physically cannot fetch or update data for Bed #50 on Floor 2.

## 9. SUCCESS CRITERIA
The prompt is successful if the generated code:
1. Starts with `streamlit run app.py` and shows a login screen.
2. Allows Alice (Floor 1 Nurse) to edit Beds on Floor 1, but hides Floor 2.
3. Allows the Admin to see 3 floors at once and resolve a conflict from Floor 3.
4. Automatically calculates `Time_Left = Discharge_Order_Time - NOW()` and highlights overdue patients.
5. Visually displays a Conflict Badge on the table without forcing the user to read raw SQL.