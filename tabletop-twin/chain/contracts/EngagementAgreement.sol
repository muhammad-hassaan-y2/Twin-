// SPDX-License-Identifier: MIT
pragma solidity 0.8.38;

/// The directory of agents allowed to transact. A role is a bytes32 name and a principal
/// is the human who can countersign for it. Nothing else in the system can speak for a role.
interface IAgentRegistry {
    function known(bytes32 role) external view returns (bool);

    function principalOf(bytes32 role) external view returns (address);
}

/// One agreement between two agents, and the only place their word is kept.
///
/// This is deliberately not a token, and it holds no money. What it holds is the thing an
/// audit firm actually needs to survive a regulator: a record of who proposed what to whom,
/// when the other side agreed, what evidence was attested, and which named human signed the
/// judgement that a machine was not allowed to make alone. Every state change is a
/// requirement in bytecode, so "the senior signed off the valuation before the reviewer
/// looked at it" is refused by the chain rather than noticed afterwards.
contract EngagementAgreement {
    enum State {
        None,
        Proposed,
        Accepted,
        Attested,
        Settled,
        Rejected,
        Disputed
    }

    struct Agreement {
        bytes32 id;
        bytes32 fromRole;
        bytes32 toRole;
        bytes32 termsHash;
        uint256 amountCents;
        /// Non-audit work measured against the cap the calibration step derived off-chain.
        uint256 nonAuditCents;
        State state;
        uint64 deadline;
        uint64 proposedAt;
        bytes32 evidenceHash;
        address signedBy;
        uint256 gasUsed;
        string reason;
    }

    IAgentRegistry public immutable registry;

    /// Basis points of the audit fee that non-audit work may reach. Set at deployment from
    /// the derived prior, so the number that the EU text states is the number the bytecode
    /// enforces. 7000 is what the corpus said on the day this was written.
    uint256 public immutable nonAuditCapBasisPoints;

    mapping(bytes32 => Agreement) private _agreements;
    bytes32[] private _ids;
    uint256 public seq;

    event Proposed(
        uint256 indexed index,
        bytes32 indexed id,
        bytes32 fromRole,
        bytes32 toRole,
        bytes32 termsHash,
        uint256 amountCents,
        uint256 nonAuditCents,
        uint64 deadline,
        uint256 seq
    );
    event Accepted(bytes32 indexed id, bytes32 byRole, uint256 seq);
    event Attested(bytes32 indexed id, bytes32 byRole, bytes32 evidenceHash, uint256 seq);
    event Countersigned(bytes32 indexed id, address byHuman, uint256 seq);
    event Settled(bytes32 indexed id, bytes32 byRole, uint256 seq);
    event Rejected(bytes32 indexed id, bytes32 byRole, string reason, uint256 seq);
    event Disputed(bytes32 indexed id, bytes32 byRole, string reason, uint256 seq);

    error UnknownAgreement(bytes32 id);
    error EmptyTerms();
    error UnknownRole(bytes32 role);
    error NotCounterparty(bytes32 role);
    error NotProposer(bytes32 role);
    error WrongState(State have, string wanted);
    error Expired(uint64 deadline, uint64 nowTs);
    error FeeCapBreached(uint256 nonAuditCents, uint256 allowedCents);
    error HumanRequired(bytes32 id);

    constructor(address registry_, uint256 nonAuditCapBasisPoints_) {
        require(registry_ != address(0), "registry required");
        require(nonAuditCapBasisPoints_ > 0 && nonAuditCapBasisPoints_ <= 10_000, "cap in basis points");
        registry = IAgentRegistry(registry_);
        nonAuditCapBasisPoints = nonAuditCapBasisPoints_;
    }

    /// Open one. The proposer speaks for itself; the counterparty is named, not implied.
    function propose(
        bytes32 fromRole,
        bytes32 toRole,
        bytes32 termsHash,
        uint256 amountCents,
        uint256 nonAuditCents,
        uint64 deadline
    ) external returns (bytes32 id) {
        require(toRole != bytes32(0), "a counterparty is required");
        require(fromRole != bytes32(0), "a proposer is required");
        require(registry.known(fromRole), "unknown proposer");
        require(registry.known(toRole), "unknown counterparty");
        if (termsHash == bytes32(0)) revert EmptyTerms();
        if (block.timestamp > deadline) revert Expired(deadline, uint64(block.timestamp));

        // The cap is arithmetic on the derived prior, applied here rather than in the caller,
        // because the caller is the agent that would like it to pass.
        uint256 allowed = (amountCents * nonAuditCapBasisPoints) / 10_000;
        if (nonAuditCents > allowed) revert FeeCapBreached(nonAuditCents, allowed);

        id = keccak256(abi.encodePacked(msg.sender, fromRole, toRole, termsHash, seq));
        require(_agreements[id].state == State.None, "id exists");

        _agreements[id] = Agreement({
            id: id,
            fromRole: fromRole,
            toRole: toRole,
            termsHash: termsHash,
            amountCents: amountCents,
            nonAuditCents: nonAuditCents,
            state: State.Proposed,
            deadline: deadline,
            proposedAt: uint64(block.timestamp),
            evidenceHash: bytes32(0),
            signedBy: address(0),
            gasUsed: 0,
            reason: ""
        });
        _ids.push(id);
        unchecked {
            seq += 1;
        }
        emit Proposed(_ids.length - 1, id, fromRole, toRole, termsHash, amountCents, nonAuditCents, deadline, seq);
    }

    /// Only the named counterparty may agree, and only while the proposal is live.
    function accept(bytes32 id, bytes32 byRole) external {
        Agreement storage a = _require(id);
        if (byRole != a.toRole) revert NotCounterparty(byRole);
        if (a.state != State.Proposed) revert WrongState(a.state, "Proposed");
        if (block.timestamp > a.deadline) revert Expired(a.deadline, uint64(block.timestamp));
        a.state = State.Accepted;
        unchecked {
            seq += 1;
        }
        emit Accepted(id, byRole, seq);
    }

    /// The work product lands as a hash. The document itself stays off-chain; what the
    /// regulator needs is that this exact evidence existed at this moment.
    function attest(bytes32 id, bytes32 byRole, bytes32 evidenceHash) external {
        Agreement storage a = _require(id);
        if (byRole != a.fromRole) revert NotProposer(byRole);
        if (a.state != State.Accepted) revert WrongState(a.state, "Accepted");
        require(evidenceHash != bytes32(0), "evidence required");
        a.evidenceHash = evidenceHash;
        a.state = State.Attested;
        unchecked {
            seq += 1;
        }
        emit Attested(id, byRole, evidenceHash, seq);
    }

    /// The human step. Called by the principal the registry recorded for the counterparty
    /// role, which is how "a person signed this" stays a fact about a key rather than a
    /// claim in a log line.
    function countersign(bytes32 id) external {
        Agreement storage a = _require(id);
        if (a.state != State.Attested) revert WrongState(a.state, "Attested");
        address human = registry.principalOf(a.toRole);
        if (human == address(0) || msg.sender != human) revert HumanRequired(id);
        a.signedBy = msg.sender;
        unchecked {
            seq += 1;
        }
        emit Countersigned(id, msg.sender, seq);
    }

    /// Close it. No settlement without evidence and without the countersignature.
    function settle(bytes32 id, bytes32 byRole) external {
        Agreement storage a = _require(id);
        if (byRole != a.toRole) revert NotCounterparty(byRole);
        if (a.state != State.Attested) revert WrongState(a.state, "Attested");
        if (a.signedBy == address(0)) revert HumanRequired(id);
        a.state = State.Settled;
        unchecked {
            seq += 1;
        }
        emit Settled(id, byRole, seq);
    }

    /// A refusal is a first-class answer. It is recorded with who gave it, not deleted.
    function reject(bytes32 id, bytes32 byRole, string calldata reason) external {
        Agreement storage a = _require(id);
        if (byRole != a.toRole && byRole != a.fromRole) revert NotCounterparty(byRole);
        if (a.state == State.Settled || a.state == State.Rejected) revert WrongState(a.state, "open");
        a.state = State.Rejected;
        a.reason = reason;
        unchecked {
            seq += 1;
        }
        emit Rejected(id, byRole, reason, seq);
    }

    function dispute(bytes32 id, bytes32 byRole, string calldata reason) external {
        Agreement storage a = _require(id);
        if (byRole != a.toRole && byRole != a.fromRole) revert NotCounterparty(byRole);
        if (a.state == State.None) revert UnknownAgreement(id);
        a.state = State.Disputed;
        a.reason = reason;
        unchecked {
            seq += 1;
        }
        emit Disputed(id, byRole, reason, seq);
    }

    function get(bytes32 id) external view returns (Agreement memory) {
        Agreement storage a = _require(id);
        return a;
    }

    function count() external view returns (uint256) {
        return _ids.length;
    }

    function idAt(uint256 index) external view returns (bytes32) {
        require(index < _ids.length, "out of range");
        return _ids[index];
    }

    function _require(bytes32 id) private view returns (Agreement storage a) {
        a = _agreements[id];
        if (a.state == State.None && a.fromRole == bytes32(0)) revert UnknownAgreement(id);
    }
}
