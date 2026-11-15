package com.theseus.api.domain.tool.dto.request;

import com.theseus.api.domain.project.entity.ProjectAccessLevelPolicy;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.util.Set;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;

class ToolApprovalApproveRequestTest {

	private static ValidatorFactory validatorFactory;
	private static Validator validator;

	@BeforeAll
	static void setUpValidator() {
		validatorFactory = Validation.buildDefaultValidatorFactory();
		validator = validatorFactory.getValidator();
	}

	@AfterAll
	static void closeValidator() {
		validatorFactory.close();
	}

	@ParameterizedTest
	@ValueSource(ints = {1, 3, ProjectAccessLevelPolicy.MAX_MEMBER_ACCESS_LEVEL})
	@DisplayName("toolGrade within the member access level range is valid")
	void toolGradeWithinPolicyRangeIsValid(int toolGrade) {
		assertThat(validate(toolGrade)).isEmpty();
	}

	@ParameterizedTest
	@ValueSource(ints = {0, -1, ProjectAccessLevelPolicy.MAX_MEMBER_ACCESS_LEVEL + 1, 100})
	@DisplayName("toolGrade outside the member access level range is rejected")
	void toolGradeOutsidePolicyRangeIsRejected(int toolGrade) {
		assertThat(validate(toolGrade))
			.extracting(violation -> violation.getPropertyPath().toString())
			.containsExactly("toolGrade");
	}

	private Set<ConstraintViolation<ToolApprovalApproveRequest>> validate(int toolGrade) {
		ToolApprovalApproveRequest request = new ToolApprovalApproveRequest();
		ReflectionTestUtils.setField(request, "toolGrade", toolGrade);
		return validator.validate(request);
	}
}
