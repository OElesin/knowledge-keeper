import type { CreateTwinPayload, EmployeeRecord } from "../api/twins";

/**
 * Apply an EmployeeRecord from directory lookup onto the offboarding form.
 * Sets exactly 5 fields (employeeId, name, email, role, department) from the
 * record and preserves all other form fields (offboardDate, provider).
 */
export function applyLookup(
  form: CreateTwinPayload,
  record: EmployeeRecord,
): CreateTwinPayload {
  return {
    ...form,
    employeeId: record.employeeId,
    name: record.name,
    email: record.email,
    role: record.role,
    department: record.department,
  };
}
