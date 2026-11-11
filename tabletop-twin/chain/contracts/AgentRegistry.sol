// SPDX-License-Identifier: MIT
pragma solidity 0.8.38;

/// Who the firm's agents are, and which person answers for each of them.
///
/// An agent cannot be a party to an agreement until it is registered, and a role cannot be
/// countersigned for until a principal is set. Both are one-way operations from the firm's
/// own key: adding an agent is a decision somebody is accountable for, so it is an event on
/// a chain rather than a line in a config file.
contract AgentRegistry {
    struct Agent {
        bytes32 role;
        address caller;
        address principal;
        string title;
        uint64 registeredAt;
        bool active;
    }

    address public owner;
    mapping(bytes32 => Agent) private _agents;
    bytes32[] private _roles;
    /// A role that was withdrawn. It stays readable so an old agreement can still be
    /// explained, but it can never sign a new one.
    mapping(bytes32 => bool) public withdrawn;

    event Registered(bytes32 indexed role, address indexed caller, address indexed principal, string title);
    event PrincipalSet(bytes32 indexed role, address indexed principal);
    event Withdrawn(bytes32 indexed role);

    error NotOwner();
    error AlreadyRegistered(bytes32 role);
    error UnknownRole(bytes32 role);
    error ZeroAddress();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor() {
        owner = msg.sender;
    }

    function register(bytes32 role, address caller, address principal, string calldata title) external onlyOwner {
        require(role != bytes32(0), "a role name is required");
        if (caller == address(0)) revert ZeroAddress();
        if (_agents[role].registeredAt != 0) revert AlreadyRegistered(role);
        _agents[role] = Agent({
            role: role,
            caller: caller,
            principal: principal,
            title: title,
            registeredAt: uint64(block.timestamp),
            active: true
        });
        _roles.push(role);
        emit Registered(role, caller, principal, title);
    }

    /// The person may change; the role may not be quietly re-pointed at a different machine.
    function setPrincipal(bytes32 role, address principal) external onlyOwner {
        if (principal == address(0)) revert ZeroAddress();
        if (_agents[role].registeredAt == 0) revert UnknownRole(role);
        _agents[role].principal = principal;
        emit PrincipalSet(role, principal);
    }

    function withdraw(bytes32 role) external onlyOwner {
        if (_agents[role].registeredAt == 0) revert UnknownRole(role);
        _agents[role].active = false;
        withdrawn[role] = true;
        emit Withdrawn(role);
    }

    /// A party to an agreement must be a live role.
    function known(bytes32 role) external view returns (bool) {
        return _agents[role].registeredAt != 0 && _agents[role].active && !withdrawn[role];
    }

    function principalOf(bytes32 role) external view returns (address) {
        return _agents[role].principal;
    }

    function callerOf(bytes32 role) external view returns (address) {
        return _agents[role].caller;
    }

    function agent(bytes32 role) external view returns (Agent memory) {
        if (_agents[role].registeredAt == 0) revert UnknownRole(role);
        return _agents[role];
    }

    function size() external view returns (uint256) {
        return _roles.length;
    }

    function roleAt(uint256 index) external view returns (bytes32) {
        require(index < _roles.length, "out of range");
        return _roles[index];
    }
}
