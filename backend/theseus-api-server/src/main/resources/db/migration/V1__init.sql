-- Theseus API 서버 초기 스키마(baseline)입니다.
-- Flyway 도입 시점의 JPA 엔티티를 MySQL 8.4에서 Hibernate schema export로 추출했습니다.
-- 이후 스키마 변경은 이 파일을 고치지 말고 V2__*.sql 같은 새 마이그레이션으로 추가합니다.
-- 기존 ddl-auto 기반 DB는 spring.flyway.baseline-on-migrate로 이 버전을 적용된 것으로 기록합니다.


create table billing_usages (
    completion_tokens bigint not null,
    created_at datetime(6) not null,
    id bigint not null auto_increment,
    project_id bigint not null,
    prompt_tokens bigint not null,
    reported_at datetime(6) not null,
    total_tokens bigint not null,
    user_id bigint not null,
    model_name varchar(120) not null,
    idempotency_key varchar(255),
    usage_payload_json LONGTEXT not null,
    primary key (id)
) engine=InnoDB;

create table chat_messages (
    message_order integer not null,
    chat_session_id bigint not null,
    created_at datetime(6) not null,
    id bigint not null auto_increment,
    tool_id bigint,
    tool_plan_id bigint,
    tool_plan_run_id bigint,
    content MEDIUMTEXT not null,
    idempotency_key varchar(255),
    content_type VARCHAR(30) DEFAULT 'TEXT' not null,
    message_type VARCHAR(50) DEFAULT 'CHAT' not null,
    sender_type enum ('ASSISTANT','SYSTEM','USER') not null,
    primary key (id)
) engine=InnoDB;

create table chat_sessions (
    closed_at datetime(6),
    created_at datetime(6) not null,
    id bigint not null auto_increment,
    project_id bigint not null,
    project_member_id bigint not null,
    updated_at datetime(6) not null,
    title varchar(150),
    primary key (id)
) engine=InnoDB;

create table project_members (
    access_level integer not null,
    can_create_tool bit not null,
    can_delete_tool bit not null,
    can_update_tool bit not null,
    can_use_tool bit not null,
    created_at datetime(6) not null,
    created_by_user_id bigint,
    id bigint not null auto_increment,
    project_id bigint not null,
    updated_at datetime(6) not null,
    user_id bigint not null,
    status varchar(30) not null,
    project_role enum ('ADMIN','MANAGER','MEMBER') not null,
    primary key (id)
) engine=InnoDB;

create table projects (
    created_at datetime(6) not null,
    created_by_user_id bigint not null,
    id bigint not null auto_increment,
    project_admin_user_id bigint not null,
    updated_at datetime(6) not null,
    name varchar(100) not null,
    description TEXT,
    status enum ('ACTIVE','INACTIVE') not null,
    primary key (id)
) engine=InnoDB;

create table remote_workspaces (
    allow_write_execution bit not null,
    port integer not null,
    created_at datetime(6) not null,
    created_by_project_member_id bigint not null,
    id bigint not null auto_increment,
    project_id bigint not null,
    updated_at datetime(6) not null,
    name varchar(100) not null,
    username varchar(100) not null,
    base_path varchar(500) not null,
    password varchar(500),
    private_key_path varchar(500),
    host varchar(255) not null,
    status enum ('ACTIVE','DELETED') not null,
    primary key (id)
) engine=InnoDB;

create table tool_approvals (
    request_number integer not null,
    id bigint not null auto_increment,
    requested_at datetime(6) not null,
    requested_by_project_member_id bigint not null,
    reviewed_at datetime(6),
    reviewed_by_project_member_id bigint,
    tool_id bigint,
    tool_plan_id bigint,
    review_feedback TEXT,
    approval_status VARCHAR(30) DEFAULT 'PENDING' not null,
    primary key (id)
) engine=InnoDB;

create table tool_plan_groups (
    approved_tool_plan_id bigint,
    chat_session_id bigint not null,
    created_at datetime(6) not null,
    created_by_project_member_id bigint not null,
    created_tool_id bigint,
    id bigint not null auto_increment,
    latest_tool_plan_id bigint,
    project_id bigint not null,
    updated_at datetime(6) not null,
    status VARCHAR(30) DEFAULT 'PLANNING' not null,
    primary key (id)
) engine=InnoDB;

create table tool_plan_runs (
    base_tool_plan_id bigint,
    chat_session_id bigint not null,
    completed_at datetime(6),
    created_at datetime(6) not null,
    id bigint not null auto_increment,
    last_event_sequence bigint,
    plan_group_id bigint,
    project_id bigint not null,
    remote_workspace_id bigint,
    requested_at datetime(6) not null,
    requested_by_project_member_id bigint not null,
    result_tool_plan_id bigint,
    updated_at datetime(6) not null,
    user_message_id bigint,
    run_id varchar(64) not null,
    last_event_type varchar(80),
    error_code varchar(120),
    error_message TEXT,
    history_snapshot_json LONGTEXT,
    request_payload_json LONGTEXT,
    mode VARCHAR(30) DEFAULT 'PLAN' not null,
    request_type enum ('BUILD_TOOL','GENERATE_PLAN','REGENERATE_PLAN') not null,
    status VARCHAR(30) DEFAULT 'REQUESTED' not null,
    primary key (id)
) engine=InnoDB;

create table tool_plans (
    base_tool_plan_id bigint,
    chat_session_id bigint not null,
    created_at datetime(6) not null,
    created_by_project_member_id bigint not null,
    id bigint not null auto_increment,
    plan_group_id bigint not null,
    plan_version bigint not null,
    project_id bigint not null,
    updated_at datetime(6) not null,
    plan_snapshot LONGTEXT not null,
    raw_markdown LONGTEXT not null,
    requested_prompt LONGTEXT,
    structured_plan_json LONGTEXT not null,
    mode VARCHAR(30) DEFAULT 'PLAN' not null,
    status VARCHAR(30) DEFAULT 'REVIEW' not null,
    primary key (id)
) engine=InnoDB;

create table tool_usage_logs (
    id bigint not null auto_increment,
    project_id bigint not null,
    tool_id bigint not null,
    used_at datetime(6) not null,
    used_by_project_member_id bigint not null,
    error_message TEXT,
    status enum ('FAILED','SUCCESS') not null,
    primary key (id)
) engine=InnoDB;

create table tools (
    tool_grade INT UNSIGNED,
    chat_session_id bigint not null,
    created_at datetime(6) not null,
    created_by_project_member_id bigint not null,
    id bigint not null auto_increment,
    project_id bigint not null,
    source_tool_plan_id bigint,
    updated_at datetime(6) not null,
    display_name varchar(30),
    file_name varchar(120) not null,
    module_name varchar(160),
    artifact_path varchar(500),
    code_snapshot LONGTEXT,
    display_description TEXT,
    metadata_json LONGTEXT,
    status VARCHAR(30) DEFAULT 'APPROVED' not null,
    primary key (id)
) engine=InnoDB;

create table users (
    created_at datetime(6) not null,
    id bigint not null auto_increment,
    updated_at datetime(6) not null,
    employee_number varchar(50) not null,
    email varchar(100),
    name varchar(100) not null,
    password varchar(255) not null,
    status enum ('ACTIVE','INACTIVE') not null,
    system_role enum ('SUPER_ADMIN','USER') not null,
    primary key (id)
) engine=InnoDB;

create index idx_billing_usages_user_reported_at
   on billing_usages (user_id, reported_at);

create index idx_billing_usages_project_reported_at
   on billing_usages (project_id, reported_at);

alter table billing_usages
   add constraint uk_billing_usages_idempotency_key unique (idempotency_key);

create index idx_chat_messages_session_order
   on chat_messages (chat_session_id, message_order);

create index idx_chat_messages_tool_order
   on chat_messages (tool_id, message_order);

create index idx_chat_messages_tool_plan_order
   on chat_messages (tool_plan_id, message_order);

create index idx_chat_messages_tool_plan_run
   on chat_messages (tool_plan_run_id);

alter table chat_messages
   add constraint uk_chat_messages_session_order unique (chat_session_id, message_order);

alter table chat_messages
   add constraint uk_chat_messages_idempotency_key unique (idempotency_key);

create index idx_chat_sessions_project_member
   on chat_sessions (project_member_id);

alter table project_members
   add constraint uk_project_members_project_user unique (project_id, user_id);

create index idx_remote_workspaces_project_status
   on remote_workspaces (project_id, status);

create index idx_tool_approvals_tool_status
   on tool_approvals (tool_id, approval_status);

create index idx_tool_approvals_plan_status
   on tool_approvals (tool_plan_id, approval_status);

alter table tool_approvals
   add constraint uk_tool_approvals_tool_request unique (tool_id, request_number);

alter table tool_approvals
   add constraint uk_tool_approvals_plan_request unique (tool_plan_id, request_number);

create index idx_tool_plan_groups_project_session
   on tool_plan_groups (project_id, chat_session_id);

create index idx_tool_plan_runs_project_session_status
   on tool_plan_runs (project_id, chat_session_id, status);

alter table tool_plan_runs
   add constraint uk_tool_plan_runs_run_id unique (run_id);

create index idx_tool_plans_group_status
   on tool_plans (plan_group_id, status);

alter table tool_plans
   add constraint uk_tool_plans_group_version unique (plan_group_id, plan_version);

create index idx_tool_usage_logs_project_used_at
   on tool_usage_logs (project_id, used_at);

create index idx_tool_usage_logs_project_status
   on tool_usage_logs (project_id, status);

create index idx_tools_chat_session_status
   on tools (chat_session_id, status);

create index idx_tools_project_status
   on tools (project_id, status);

alter table tools
   add constraint uk_tools_project_file_name unique (project_id, file_name);

alter table tools
   add constraint uk_tools_source_tool_plan unique (source_tool_plan_id);

alter table users
   add constraint uk_users_employee_number unique (employee_number);

alter table users
   add constraint uk_users_email unique (email);

alter table billing_usages
   add constraint FKfj8d71q8f35ud9xgnkol4pkus
   foreign key (project_id)
   references projects (id);

alter table billing_usages
   add constraint FKpo9hj6gmin0gskclv89aihol4
   foreign key (user_id)
   references users (id);

alter table chat_messages
   add constraint fk_chat_messages_chat_session
   foreign key (chat_session_id)
   references chat_sessions (id);

alter table chat_messages
   add constraint fk_chat_messages_tool
   foreign key (tool_id)
   references tools (id);

alter table chat_messages
   add constraint fk_chat_messages_tool_plan
   foreign key (tool_plan_id)
   references tool_plans (id);

alter table chat_messages
   add constraint fk_chat_messages_tool_plan_run
   foreign key (tool_plan_run_id)
   references tool_plan_runs (id);

alter table chat_sessions
   add constraint FKped6akl79n625egwltmyeowf6
   foreign key (project_id)
   references projects (id);

alter table chat_sessions
   add constraint FKjdct0d8rnf3aj1lgegdgdmhrk
   foreign key (project_member_id)
   references project_members (id);

alter table project_members
   add constraint FKthaj3la98xymun5yda1wme7wm
   foreign key (created_by_user_id)
   references users (id);

alter table project_members
   add constraint FKdki1sp2homqsdcvqm9yrix31g
   foreign key (project_id)
   references projects (id);

alter table project_members
   add constraint FKgul2el0qjk5lsvig3wgajwm77
   foreign key (user_id)
   references users (id);

alter table projects
   add constraint FKemfmoe3hr2tp240bblen575hg
   foreign key (created_by_user_id)
   references users (id);

alter table projects
   add constraint FK3xl2rqy17y3m3g4qexm94wea1
   foreign key (project_admin_user_id)
   references users (id);

alter table remote_workspaces
   add constraint fk_remote_workspaces_created_by_project_member
   foreign key (created_by_project_member_id)
   references project_members (id);

alter table remote_workspaces
   add constraint fk_remote_workspaces_project
   foreign key (project_id)
   references projects (id);

alter table tool_approvals
   add constraint fk_tool_approvals_requested_by_project_member
   foreign key (requested_by_project_member_id)
   references project_members (id);

alter table tool_approvals
   add constraint fk_tool_approvals_reviewed_by_project_member
   foreign key (reviewed_by_project_member_id)
   references project_members (id);

alter table tool_approvals
   add constraint fk_tool_approvals_tool
   foreign key (tool_id)
   references tools (id);

alter table tool_approvals
   add constraint fk_tool_approvals_tool_plan
   foreign key (tool_plan_id)
   references tool_plans (id);

alter table tool_plan_groups
   add constraint fk_tool_plan_groups_approved_tool_plan
   foreign key (approved_tool_plan_id)
   references tool_plans (id);

alter table tool_plan_groups
   add constraint fk_tool_plan_groups_chat_session
   foreign key (chat_session_id)
   references chat_sessions (id);

alter table tool_plan_groups
   add constraint fk_tool_plan_groups_created_by_project_member
   foreign key (created_by_project_member_id)
   references project_members (id);

alter table tool_plan_groups
   add constraint fk_tool_plan_groups_created_tool
   foreign key (created_tool_id)
   references tools (id);

alter table tool_plan_groups
   add constraint fk_tool_plan_groups_latest_tool_plan
   foreign key (latest_tool_plan_id)
   references tool_plans (id);

alter table tool_plan_groups
   add constraint fk_tool_plan_groups_project
   foreign key (project_id)
   references projects (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_base_tool_plan
   foreign key (base_tool_plan_id)
   references tool_plans (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_chat_session
   foreign key (chat_session_id)
   references chat_sessions (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_group
   foreign key (plan_group_id)
   references tool_plan_groups (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_project
   foreign key (project_id)
   references projects (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_remote_workspace
   foreign key (remote_workspace_id)
   references remote_workspaces (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_requested_by_project_member
   foreign key (requested_by_project_member_id)
   references project_members (id);

alter table tool_plan_runs
   add constraint fk_tool_plan_runs_result_tool_plan
   foreign key (result_tool_plan_id)
   references tool_plans (id);

alter table tool_plans
   add constraint fk_tool_plans_base_tool_plan
   foreign key (base_tool_plan_id)
   references tool_plans (id);

alter table tool_plans
   add constraint fk_tool_plans_chat_session
   foreign key (chat_session_id)
   references chat_sessions (id);

alter table tool_plans
   add constraint fk_tool_plans_created_by_project_member
   foreign key (created_by_project_member_id)
   references project_members (id);

alter table tool_plans
   add constraint fk_tool_plans_group
   foreign key (plan_group_id)
   references tool_plan_groups (id);

alter table tool_plans
   add constraint fk_tool_plans_project
   foreign key (project_id)
   references projects (id);

alter table tool_usage_logs
   add constraint fk_tool_usage_logs_project
   foreign key (project_id)
   references projects (id);

alter table tool_usage_logs
   add constraint fk_tool_usage_logs_tool
   foreign key (tool_id)
   references tools (id);

alter table tool_usage_logs
   add constraint fk_tool_usage_logs_used_by_project_member
   foreign key (used_by_project_member_id)
   references project_members (id);

alter table tools
   add constraint fk_tools_chat_session
   foreign key (chat_session_id)
   references chat_sessions (id);

alter table tools
   add constraint fk_tools_created_by_project_member
   foreign key (created_by_project_member_id)
   references project_members (id);

alter table tools
   add constraint fk_tools_project
   foreign key (project_id)
   references projects (id);

alter table tools
   add constraint fk_tools_source_tool_plan
   foreign key (source_tool_plan_id)
   references tool_plans (id);
