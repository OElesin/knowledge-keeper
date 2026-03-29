/**
 * Feature: directory-employee-lookup
 * Property 9: Auto-fill field mapping preserves unrelated fields
 *
 * For any EmployeeRecord returned by the lookup API and any pre-existing form
 * state, the auto-fill operation SHALL set exactly the five fields (employeeId,
 * name, email, role, department) to the values from the EmployeeRecord, and
 * SHALL leave offboardDate and provider at their pre-existing values.
 *
 * Validates: Requirements 6.3, 6.4
 */
import { describe, it, expect } from "vitest";
import fc from "fast-check";
import { applyLookup } from "../applyLookup";
import type { CreateTwinPayload, EmployeeRecord } from "../../api/twins";

const providerArb = fc.constantFrom("google", "microsoft", "upload") as fc.Arbitrary<
  "google" | "microsoft" | "upload"
>;

const formArb: fc.Arbitrary<CreateTwinPayload> = fc.record({
  employeeId: fc.string(),
  name: fc.string(),
  email: fc.string(),
  role: fc.string(),
  department: fc.string(),
  offboardDate: fc.string(),
  provider: providerArb,
});

const employeeRecordArb: fc.Arbitrary<EmployeeRecord> = fc.record({
  employeeId: fc.string(),
  name: fc.string(),
  email: fc.string(),
  role: fc.string(),
  department: fc.string(),
});

describe("Property 9: Auto-fill field mapping preserves unrelated fields", () => {
  it("sets exactly 5 fields from EmployeeRecord and preserves offboardDate and provider", () => {
    fc.assert(
      fc.property(formArb, employeeRecordArb, (form, record) => {
        const result = applyLookup(form, record);

        // The 5 lookup fields must match the EmployeeRecord
        expect(result.employeeId).toBe(record.employeeId);
        expect(result.name).toBe(record.name);
        expect(result.email).toBe(record.email);
        expect(result.role).toBe(record.role);
        expect(result.department).toBe(record.department);

        // offboardDate and provider must be unchanged from original form
        expect(result.offboardDate).toBe(form.offboardDate);
        expect(result.provider).toBe(form.provider);
      }),
      { numRuns: 100 },
    );
  });

  it("result has exactly the same keys as the input form", () => {
    fc.assert(
      fc.property(formArb, employeeRecordArb, (form, record) => {
        const result = applyLookup(form, record);
        const resultKeys = Object.keys(result).sort();
        const formKeys = Object.keys(form).sort();
        expect(resultKeys).toEqual(formKeys);
      }),
      { numRuns: 100 },
    );
  });

  it("is idempotent — applying the same record twice yields the same result", () => {
    fc.assert(
      fc.property(formArb, employeeRecordArb, (form, record) => {
        const once = applyLookup(form, record);
        const twice = applyLookup(once, record);
        expect(twice).toEqual(once);
      }),
      { numRuns: 100 },
    );
  });
});
