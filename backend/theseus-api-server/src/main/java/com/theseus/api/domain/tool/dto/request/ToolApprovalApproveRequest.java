package com.theseus.api.domain.tool.dto.request;

import com.theseus.api.domain.project.entity.ProjectAccessLevelPolicy;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Getter;

@Getter
public class ToolApprovalApproveRequest {

	@Min(ProjectAccessLevelPolicy.DEFAULT_MEMBER_ACCESS_LEVEL)
	@Max(ProjectAccessLevelPolicy.MAX_MEMBER_ACCESS_LEVEL)
	private Integer toolGrade;

	private String reviewFeedback;
}
